"""Phase 2: the desktop's core packages and services.

From the live ISO this installs into the system phase 1 left at /mnt, on
an installed system it goes through sudo.
"""

from pathlib import Path

from .common import LIVE, install, packages, run, skipped

SERVICES = {  # package: its service
    "networkmanager": "NetworkManager",
    "bluez": "bluetooth",
    "power-profiles-daemon": "power-profiles-daemon",
}
USER_UNITS = {  # package: its unit, for every user's session
    "hyprpolkitagent": "hyprpolkitagent",
    # gcr-4's, which gnome-keyring brings: the dotfiles point SSH_AUTH_SOCK
    # at it, since gnome-keyring 46 has no SSH agent of its own.
    "gnome-keyring": "gcr-ssh-agent.socket",
}


def main() -> None:
    """Install packages/core.txt and enable the services it needs."""
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
