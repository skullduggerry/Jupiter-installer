"""Unlocking the encrypted system with the TPM: phase 4's last step.

Where Secure Boot is on with this system's own keys and the kernel image
they signed started this boot, the root volume gets a TPM slot bound to
PCR 7 (Secure Boot's state and keys) and to PCR 15 still zero, which
systemd-cryptsetup extends with the volume key as soon as it opens a volume
(tpm2-measure-pcr in /etc/crypttab): the TPM gives the key out only before
any volume is open, in this initramfs, so a volume an attacker put in place
of this one, with its UUID, cannot lead to it. fixate-volume-key makes the
initramfs refuse such a volume outright, so no passphrase is ever typed into
the system on it. A recovery key is added once, and shown once.

Run again (bootstrap.sh 4), it changes nothing while the binding still
matches the TPM's PCR 7, and enrols again where a firmware or dbx update
changed it. Where something is missing (no TPM, Secure Boot off, keys not
enrolled), it says what, and the passphrase keeps unlocking the disk.
"""

import hashlib
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import secureboot
from .common import log, output, run, succeeds, warn

TPM = Path("/sys/class/tpm/tpm0")
SYSTEMD_VENDOR = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
# Set by systemd-stub: this boot came from a unified kernel image.
STUB_INFO = secureboot.EFIVARS / f"StubInfo-{SYSTEMD_VENDOR}"
CRYPTTAB = Path("/etc/crypttab")
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
    changed = _fixate(name, device) or changed
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
            "with `sudo sbctl create-keys`, then run bootstrap.sh 4 again."
        ]
    if firmware == "setup":
        enroll = ["sudo", "sbctl", "enroll-keys", "--microsoft"]
        if not succeeds(*enroll):
            return ["sbctl could not enrol the keys: see what it said above."]
        log("Enrolled the Secure Boot keys, with Microsoft's")
        return [
            "Reboot, turn Secure Boot on in the firmware's setup if it is "
            "not, then run bootstrap.sh 4 again to bind the disk to the TPM."
        ]
    if firmware == "off":
        return [
            "Secure Boot is off: turn it on in the firmware's setup, then "
            "run bootstrap.sh 4 again. If the firmware still has its own "
            "keys, erase them there first (Setup Mode); phase 4 enrols "
            "this system's."
        ]
    if not STUB_INFO.exists():
        return [
            "This boot did not start from the signed kernel image "
            f"({secureboot.UKI}): boot it, then run bootstrap.sh 4 again."
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


def _fixate(name: str, device: str) -> bool:
    """The root's crypttab line tries the TPM slot (tpm2-device=auto, which
    systemd-cryptsetup needs to try it at all, and which waits for a TPM, so
    only a system with a TPM slot gets it), measures its volume key into
    PCR 15 and expects the key it has; True if the line changed (and the
    image was built again)."""
    uuid = output("sudo", "cryptsetup", "luksUUID", device).strip()
    lines = CRYPTTAB.read_text().splitlines(keepends=True)
    for index, line in enumerate(lines):
        fields = line.split()
        if not fields or fields[0] != name:
            continue
        options = fields[3].split(",") if len(fields) > 3 else []
        # systemd-cryptsetup tries the TPM slot only when told to.
        wanted = ["tpm2-device=auto", "tpm2-measure-pcr=yes"]
        key = _volume_key_id(name, uuid)
        if key:
            wanted.append(f"fixate-volume-key={key}")
        kept = [
            option
            for option in options
            if option.split("=")[0]
            not in {"tpm2-device", "tpm2-measure-pcr", "fixate-volume-key"}
        ]
        new = [*kept, *wanted]
        if new == options:
            return False
        fields[2:] = [fields[2] if len(fields) > 2 else "none", ",".join(new)]
        lines[index] = " ".join(fields) + "\n"
        break
    else:
        return False
    _install(CRYPTTAB, "".join(lines))
    run("sudo", "mkinitcpio", "--allpresets")
    if not key:
        log(
            "Reboot and run bootstrap.sh 4 again: the volume key's hash is "
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


def _install(path: Path, text: str) -> None:
    """Replace a root-owned file, keeping the old one as path~."""
    with tempfile.NamedTemporaryFile("w", suffix=path.suffix) as new:
        new.write(text)
        new.flush()
        run("sudo", "install", "-b", "-m", "0600", new.name, path)
