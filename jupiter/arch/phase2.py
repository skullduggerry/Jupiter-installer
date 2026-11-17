"""Phase 2 on Arch: the desktop's core packages (arch/packages/core.txt)
and services.

From the live ISO this installs into the system phase 1 left at /mnt, on
an installed system it goes through sudo.
"""

import os
from pathlib import Path

from ..common import LIVE, output, run
from .common import install, packages, skipped

SERVICES = {  # package: its service
    "networkmanager": "NetworkManager",
    "bluez": "bluetooth",
    "power-profiles-daemon": "power-profiles-daemon",
    "reflector": "reflector.timer",
}
USER_UNITS = {  # package: its unit, for every user's session
    "hyprpolkitagent": "hyprpolkitagent",
    # gcr-4's, which gnome-keyring brings: the dotfiles point SSH_AUTH_SOCK
    # at it, since gnome-keyring 46 has no SSH agent of its own.
    "gnome-keyring": "gcr-ssh-agent.socket",
}

# systemd's TPM measurements, which only something bound to the TPM reads:
# without an encrypted disk (phase 1 asked) nothing is, and they cost every
# boot half a second. An encrypted system keeps them for its TPM binding.
TPM_UNITS = [
    "systemd-tpm2-setup-early.service",
    "systemd-tpm2-setup.service",
    "systemd-pcrphase-initrd.service",
    "systemd-pcrphase-sysinit.service",
    "systemd-pcrphase.service",
    "systemd-pcrmachine.service",
    "systemd-pcrproduct.service",
    "systemd-pcrlogin@.service",
    "systemd-pcrnvdone.service",
    "systemd-pcrosseparator.service",
]

REGDOM = "/etc/conf.d/wireless-regdom"
# The folders xdg-user-dirs makes in a home at its first login, and points
# apps at: Downloads, and Screenshots as the pictures folder, where hyprshot
# saves. The others (Documents, Music, ...) are not made, so a folder synced
# from elsewhere, such as Nextcloud's, can take their names.
USER_DIRS = "/etc/xdg/user-dirs.defaults"
USER_DIRS_DEFAULTS = """\
# Written by Jupiter's phase 2: the folders a new home gets.
DOWNLOAD=Downloads
PICTURES=Screenshots
"""


def country(root: Path) -> str | None:
    """The country of the time zone set in root, from tzdata's zone.tab."""
    localtime = root / "etc/localtime"
    if not localtime.is_symlink():
        return None
    zone = os.readlink(localtime).partition("zoneinfo/")[2]
    table = (root / "usr/share/zoneinfo/zone.tab").read_text()
    for line in table.splitlines():
        fields = line.split("\t")
        if len(fields) > 2 and fields[2] == zone:
            return fields[0]
    return None


def encrypted() -> bool:
    """Whether a disk here holds a LUKS volume, which a TPM may unlock:
    phase 1's, unless encryption was declined, or one set up by hand."""
    return "crypto_LUKS" in output("lsblk", "--noheadings", "-o", "FSTYPE")


def main() -> None:
    """Install arch/packages/core.txt and enable the services it needs."""
    if LIVE and not Path("/mnt").is_mount():
        raise SystemExit("Run phase 1 first, or mount the new system at /mnt.")
    target = ["arch-chroot", "-S", "/mnt"] if LIVE else ["sudo"]
    run(*target, "pacman", "-Syu", "--noconfirm")
    pacman = [*target, "pacman", "-S", "--needed", "--noconfirm"]
    install(pacman, packages("core.txt"))
    services = [unit for name, unit in SERVICES.items() if name not in skipped]
    run(*target, "systemctl", "enable", *services)
    units = [unit for name, unit in USER_UNITS.items() if name not in skipped]
    if units:
        run(*target, "systemctl", "--global", "enable", *units)
    if "xdg-user-dirs" not in skipped:
        write = f"cat > {USER_DIRS}"
        run(*target, "sh", "-c", write, data=USER_DIRS_DEFAULTS)
    if not encrypted():
        run(*target, "systemctl", "mask", *TPM_UNITS)
    # Wi-Fi drivers that do not set their country themselves use the
    # world's rules otherwise: lower power, narrower channels on 5 GHz.
    code = country(Path("/mnt") if LIVE else Path("/"))
    if code and "wireless-regdb" not in skipped:
        line = f'WIRELESS_REGDOM="{code}"'
        run(*target, "sed", "-i", f"s/^#{line}$/{line}/", REGDOM)
