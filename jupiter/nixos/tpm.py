"""Unlocking the encrypted system with the TPM on NixOS: phase 4's last step.

The binding is Arch's (jupiter/tpm.py says what it guards against and how):
a TPM slot bound to PCR 7 and PCR 15 still zero, a recovery key added once,
a header backup offered. What differs is the root's crypttab line, which the
flake declares (nixos/base.nix): rather than editing /etc/crypttab and
building the image again, this records in hosts/<name>/settings.json that
the volume has a TPM slot (tpm2-device=auto) and the hash of its volume key
(fixate-volume-key), and rebuilds the system (phase 2). The signed image a
boot must start from is lanzaboote's. Run again, it changes nothing while
the binding still matches PCR 7.
"""

import subprocess

from .. import tpm as core
from ..common import log, output, warn
from . import system
from .common import HOSTS, host, read_settings, write_settings

IMAGE = "a kernel image lanzaboote signed (the system's newest generation)"


def main() -> None:
    """Bind the root volume to the TPM, or say what is still missing."""
    volume = core.root_volume()
    if volume is None:
        return
    name, device = volume
    if not core.has_tpm2():
        log("No TPM 2.0 here: the passphrase unlocks the disk at boot")
        return
    left = core.missing(IMAGE)
    if left:
        for step in left:
            warn(step)
        warn("Until then the passphrase unlocks the disk at boot.")
        return
    changed = core.bind(device)
    changed = _declare(name, device) or changed
    changed = core.recovery(device) or changed
    if changed:
        core.header_backup(device)
    else:
        log("The TPM unlocks the disk; nothing to change")


def _declare(name: str, device: str) -> bool:
    """Record in this machine's settings that the root has a TPM slot, and
    its volume key's hash once it is measured, and rebuild the system with
    them in the initrd's crypttab; True if they changed. tpm2-device=auto
    waits for a TPM, so only a system with a TPM slot gets it."""
    machine = host()
    old = read_settings(machine)
    uuid = output("sudo", "cryptsetup", "luksUUID", device).strip()
    key = core.volume_key_id(name, uuid) or old.get("volumeKey")
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
            "Reboot and run bootstrap.sh 4 again: the volume key's hash is "
            "measured from the next boot on"
        )
    return True
