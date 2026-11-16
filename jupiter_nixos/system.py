"""Phase 2: the system, rebuilt from this repo with nixos-rebuild.

What the Arch installer's phases 2 and 3 install with pacman and paru, and
much of what its phase 4 sets up as root, the flake declares (nixos/); this
builds this machine's configuration (hosts/<hostname>/) and switches to it.
Run it again after changing nixos/ or the settings, and after pulling an
update of this repo, whose flake.lock pins nixpkgs and the dotfiles' root
files: `bootstrap.sh 2` pulls and rebuilds. nixos-rebuild evaluates and
builds as you, and asks sudo for the switch alone: as root, git refuses a
clone in your home, which is yours.
"""

from .common import INSTALLER_DIR, host, run


def main() -> None:
    """Build this machine's configuration and switch to it."""
    rebuild(host())


def rebuild(name: str) -> None:
    """nixos-rebuild switch to hosts/<name>."""
    run(
        "nixos-rebuild", "switch", "--sudo",
        "--flake", f"{INSTALLER_DIR}#{name}",
    )  # fmt: skip
