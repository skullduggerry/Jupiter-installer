"""Unlocking the encrypted system with the TPM: phase 3's last step.

Where Secure Boot is on with this system's own keys and a kernel image they
signed (lanzaboote's) started this boot, the root volume gets a TPM slot
bound to PCR 7 (Secure Boot's state and keys) and to PCR 15 still zero,
which systemd-cryptsetup extends with the volume key as soon as it opens a
volume (tpm2-measure-pcr in the initrd's crypttab, nixos/base.nix): the TPM
gives the key out only before any volume is open, in this initrd, so a
volume an attacker put in place of this one, with its UUID, cannot lead to
it. The root's crypttab line is declared, so this step records in
hosts/<name>/settings.json that the volume has a TPM slot (tpm2-device=auto)
and the hash of its volume key (fixate-volume-key, with which the initrd
refuses any other volume, so no passphrase is ever typed into a system on
one), and rebuilds the system (phase 2). A recovery key is added once, and
shown once.

Run again (bootstrap.sh 3), it changes nothing while the binding still
matches the TPM's PCR 7, and enrols again where a firmware or dbx update
changed it. Where something is missing (no TPM, Secure Boot off, keys not
enrolled), it says what, and the passphrase keeps unlocking the disk.
"""

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path
from typing import Any

from . import secureboot, system
from .common import (
    HOSTS,
    host,
    log,
    output,
    read_settings,
    run,
    succeeds,
    warn,
    write_settings,
)

TPM = Path("/sys/class/tpm/tpm0")
SYSTEMD_VENDOR = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
# Set by systemd-stub: this boot came from a unified kernel image.
STUB_INFO = secureboot.EFIVARS / f"StubInfo-{SYSTEMD_VENDOR}"
MEASURE_LOG = Path("/run/log/systemd/tpm2-measure.log")
ZERO = "0" * 64
# Always given: systemd-cryptenroll 262 binds to no PCRs at all without it.
PCRS = f"7+15:sha256={ZERO}"
TPM_CC_POLICY_PCR = 0x0000017F
TPM_ALG_SHA256 = 0x000B

RECOVERY_HELP = """\
A recovery key opens the disk where the TPM will not (after a firmware
update, say) and you have forgotten the passphrase. It is shown once below
and saved nowhere: write it down or photograph it, and keep it off this
computer."""
BACKUP_HELP = """\
Keep a copy of the disk's LUKS header off this computer, with the recovery
key: if the header is damaged, nothing else opens the disk. Anyone with the
copy and a passphrase that was valid when it was made can open the disk,
even after you change the passphrase."""


def main() -> None:
    """Bind the root volume to the TPM, or say what is still missing."""
    volume = root_volume()
    if volume is None:
        return
    name, device = volume
    if not (TPM / "tpm_version_major").exists() or (
        (TPM / "tpm_version_major").read_text().strip() != "2"
    ):
        log("No TPM 2.0 here: the passphrase unlocks the disk at boot")
        return
    left = _missing()
    if left:
        for step in left:
            warn(step)
        warn("Until then the passphrase unlocks the disk at boot.")
        return
    changed = _bind(device)
    changed = _declare(name, device) or changed
    changed = _recovery(device) or changed
    if changed:
        _header_backup(device)
    else:
        log("The TPM unlocks the disk; nothing to change")


def root_volume() -> tuple[str, str] | None:
    """The LUKS volume under /, by its name and its partition."""
    source = output("findmnt", "--noheadings", "-o", "SOURCE", "/").strip()
    mapped = source.split("[", 1)[0]  # Btrfs adds the subvolume: [/@]
    if not mapped.startswith("/dev/mapper/"):
        return None
    lines = output(
        "lsblk", "--noheadings", "--inverse", "--list", "--paths",
        "-o", "PATH,FSTYPE", mapped,
    )  # fmt: skip
    for line in lines.splitlines():
        fields = line.split()
        if fields[1:] == ["crypto_LUKS"]:
            return mapped.removeprefix("/dev/mapper/"), fields[0]
    return None


def _missing() -> list[str]:
    """What the TPM binding still needs, as steps for the user."""
    firmware = secureboot.state()
    if firmware == "none":
        return ["This firmware has no Secure Boot, which the TPM needs."]
    status = json.loads(output("sudo", "sbctl", "status", "--json"))
    if not status.get("installed"):
        return [
            "This system has no Secure Boot keys of its own: create them "
            "with `sudo sbctl create-keys`, then run bootstrap.sh 2 3 again."
        ]
    if firmware == "setup":
        enroll = ["sudo", "sbctl", "enroll-keys", "--microsoft"]
        if not succeeds(*enroll):
            return ["sbctl could not enrol the keys: see what it said above."]
        log("Enrolled the Secure Boot keys, with Microsoft's")
        return [
            "Reboot, turn Secure Boot on in the firmware's setup if it is "
            "not, then run bootstrap.sh 3 again to bind the disk to the TPM."
        ]
    if firmware == "off":
        return [
            "Secure Boot is off: turn it on in the firmware's setup, then "
            "run bootstrap.sh 3 again. If the firmware still has its own "
            "keys, erase them there first (Setup Mode); phase 3 enrols "
            "this system's."
        ]
    if not STUB_INFO.exists():
        return [
            "This boot did not start from a kernel image lanzaboote signed: "
            "boot the system's newest generation, then run bootstrap.sh 3 "
            "again."
        ]
    return []


def _metadata(device: str) -> dict[str, Any]:
    dump = output(
        "sudo", "cryptsetup", "luksDump", "--dump-json-metadata", device
    )
    metadata: dict[str, Any] = json.loads(dump)
    return metadata


def _tokens(device: str, kind: str) -> list[dict[str, Any]]:
    tokens = _metadata(device).get("tokens", {}).values()
    return [token for token in tokens if token.get("type") == kind]


def policy(pcr7: str) -> str:
    """The TPM2 policy digest systemd-cryptenroll binds to with PCRS: a
    PolicyPCR of PCR 7 as it is now and PCR 15 zero, in the SHA-256 bank."""
    selection = struct.pack(
        ">IHB3s", 1, TPM_ALG_SHA256, 3, bytes([0x80, 0x80, 0x00])
    )
    values = hashlib.sha256(bytes.fromhex(pcr7) + bytes.fromhex(ZERO)).digest()
    command = struct.pack(">I", TPM_CC_POLICY_PCR)
    return hashlib.sha256(bytes(32) + command + selection + values).hexdigest()


def _bind(device: str) -> bool:
    """A TPM slot for PCR 7 as it is now and PCR 15 zero; True if made."""
    pcr7 = (TPM / "pcr-sha256/7").read_text().strip().lower()
    wanted = policy(pcr7)
    tokens = _tokens(device, "systemd-tpm2")
    if any(
        token.get("tpm2-policy-hash") == wanted
        and token.get("tpm2-pcrs") == [7, 15]
        for token in tokens
    ):
        return False
    if tokens:
        log("PCR 7 changed since the TPM was enrolled: enrolling it again")
    log("Binding the disk to the TPM: type its passphrase or recovery key")
    run(
        "sudo", "systemd-cryptenroll", "--wipe-slot=tpm2",
        "--tpm2-device=auto", f"--tpm2-pcrs={PCRS}", device,
    )  # fmt: skip
    return True


def _declare(name: str, device: str) -> bool:
    """Record in this machine's settings that the root has a TPM slot, and
    its volume key's hash once it is measured, and rebuild the system with
    them in the initrd's crypttab (nixos/base.nix); True if they changed.
    tpm2-device=auto waits for a TPM, so only a system with a TPM slot gets
    it."""
    machine = host()
    old = read_settings(machine)
    uuid = output("sudo", "cryptsetup", "luksUUID", device).strip()
    key = _volume_key_id(name, uuid) or old.get("volumeKey")
    new = old | {"tpm": True, "volumeKey": key}
    if new == old:
        return False
    write_settings(HOSTS / machine, new)
    try:
        system.rebuild(machine)
    except subprocess.CalledProcessError:
        # The initrd would not have the new line: the old settings back, so
        # a rerun sees them and rebuilds again.
        write_settings(HOSTS / machine, old)
        raise
    if not key:
        log(
            "Reboot and run bootstrap.sh 3 again: the volume key's hash is "
            "measured from the next boot on"
        )
    return True


def _volume_key_id(name: str, uuid: str) -> str | None:
    """The hash of the root's volume key, as systemd-cryptsetup measured it
    into PCR 15 this boot (HMAC-SHA256 of cryptsetup:<name>:<uuid> keyed with
    the volume key), from the measurement log."""
    try:
        text = output("sudo", "cat", MEASURE_LOG)
    except subprocess.CalledProcessError:  # not measured this boot
        return None
    wanted = f"cryptsetup:{name}:{uuid}"
    for record in text.split("\x1e"):
        if not record.strip():
            continue
        try:
            entry = json.loads(record)
        except json.JSONDecodeError:
            continue
        content = entry.get("content", {})
        if entry.get("pcr") != 15 or content.get("string") != wanted:
            continue
        for digest in entry.get("digests", []):
            if digest.get("hashAlg") == "sha256":
                return str(digest["digest"])
    return None


def _recovery(device: str) -> bool:
    """A recovery key, once; True if one was added."""
    if _tokens(device, "systemd-recovery"):
        return False
    print(RECOVERY_HELP, flush=True)
    run("sudo", "systemd-cryptenroll", "--recovery-key", device)
    return True


def _header_backup(device: str) -> None:
    print(BACKUP_HELP, flush=True)
    while True:
        answer = input("Write a header backup to (a new file; empty: skip): ")
        if not answer.strip():
            return
        path = Path(answer.strip()).expanduser().absolute()
        if path.exists() or not path.parent.is_dir():
            print(f"{path} exists, or its folder does not.")
            continue
        break
    run(
        "sudo", "cryptsetup", "luksHeaderBackup", device,
        "--header-backup-file", path,
    )  # fmt: skip
    run("sudo", "chown", f"{os.getuid()}:{os.getgid()}", path)
    path.chmod(0o400)
    log(f"Wrote {path}: copy it off this computer, then delete it here")
