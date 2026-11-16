"""Secure Boot with keys of your own: the firmware's state, and what to do.

Phase 1 makes the keys on an encrypted system (sbctl's, which lanzaboote
signs with: nixos/secureboot.nix) and enrols them, Microsoft's beside them
(a graphics card's firmware is signed by Microsoft), when the firmware is in
Setup Mode: its keys erased in the firmware's menu. lanzaboote signs
systemd-boot and each generation's kernel image, its command line and
initrd inside it; nothing else is signed, so under Secure Boot only those
boot. Kernel lockdown is left off, as on Arch: it refuses nvidia-open's
modules, which are unsigned.
"""

from pathlib import Path

EFIVARS = Path("/sys/firmware/efi/efivars")
GLOBAL = "8be4df61-93ca-11d2-aa0d-00e098032b8c"  # EFI_GLOBAL_VARIABLE
SETUP_MODE_HELP = """\
The firmware is not in Setup Mode, so the Secure Boot keys this install
makes cannot be enrolled now, and the TPM cannot unlock the disk until they
are. To enrol them during the install: reboot into the firmware's setup,
erase (clear) its Secure Boot keys, save, and boot this ISO again. Or go on:
on the installed system, phase 3 says what is left."""
NO_SECURE_BOOT_HELP = """\
This firmware has no Secure Boot: an encrypted system asks for its
passphrase at every boot."""


def _flag(name: str, efivars: Path) -> bool | None:
    """An EFI global variable's one-byte value, None if it is not set."""
    try:
        data = (efivars / f"{name}-{GLOBAL}").read_bytes()
    except OSError:
        return None
    return data[4:5] == b"\x01"  # after the four bytes of attributes


def state(efivars: Path | None = None) -> str:
    """'setup' (no keys: sbctl can enrol), 'on', 'off' (keys, not
    enforced) or 'none' (no Secure Boot in this firmware). efivars: this
    machine's, or the folder given."""
    efivars = efivars or EFIVARS
    setup = _flag("SetupMode", efivars)
    if setup is None:
        return "none"
    if setup:
        return "setup"
    return "on" if _flag("SecureBoot", efivars) else "off"
