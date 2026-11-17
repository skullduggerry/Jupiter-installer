"""Phases 2 and 3 on NixOS: the system, rebuilt from this repo.

What Arch's phases 2 and 3 install with pacman and paru (the desktop, then
your packages), and much of what its phase 4 sets up as root, the flake
declares (nixos/); both phases build this machine's configuration
(hosts/<hostname>/) and switch to it, once a run however many of the two
it names. Run it again after changing nixos/ or the settings, and after an
update of this repo, whose flake.lock names the revisions of nixpkgs,
lanzaboote and the dotfiles' root files the system is built from: updates
arrive with a newer lock (docs/nixos.md, "Updates come with the repo").
nixos-rebuild evaluates and builds as you, and asks sudo for the switch
alone: as root, git refuses a clone in your home, which is yours.
"""

from ..common import INSTALLER_DIR, log, run
from .common import host

# Whether this run rebuilt already: phases 2 and 3 are the same rebuild.
rebuilt = False


def main() -> None:
    """Build this machine's configuration and switch to it, once a run."""
    global rebuilt
    if rebuilt:
        log("The system is rebuilt already: phases 2 and 3 are one here")
        return
    rebuild(host())
    rebuilt = True


def rebuild(name: str) -> None:
    """nixos-rebuild switch to hosts/<name>."""
    run(
        "nixos-rebuild", "switch", "--sudo",
        "--flake", f"{INSTALLER_DIR}#{name}",
    )  # fmt: skip
