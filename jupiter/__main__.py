"""Run the installer: python3 -m jupiter [phase ...].

The same four phases on Arch and on NixOS, told apart by jupiter/distro.py:
on Arch they are jupiter/phase1.py to phase4.py, on NixOS jupiter/nixos/,
where phases 2 and 3 are one rebuild of the system the flake declares.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from . import phase1, phase2, phase3, phase4
from .common import INSTALLER_DIR, LIVE, log, skipped, succeeds, warn
from .distro import detect
from .nixos import dotfiles as nixos_dotfiles
from .nixos import phase1 as nixos_phase1
from .nixos import system as nixos_system

PHASES = {1: phase1.main, 2: phase2.main, 3: phase3.main, 4: phase4.main}
NIXOS_PHASES = {
    1: nixos_phase1.main,
    2: nixos_system.main,
    3: nixos_system.main,
    4: nixos_dotfiles.main,
}
ISO = {
    "arch": "the Arch Linux live ISO",
    "nixos": "the NixOS installation ISO",
}
OFFLINE = (
    "No network: phases 3 and 4 download packages and the dotfiles. Connect "
    "with `nmtui` (Activate a connection, for Wi-Fi), then run "
    "~/{dir}/bootstrap.sh again."
)


def main() -> None:
    """Run the phases given on the command line, on the system this is."""
    system = detect()
    nixos = system.name == "nixos"
    # Arch's live ISO by archiso's mark, which the Arch phases read too.
    live = system.live if nixos else LIVE
    table = NIXOS_PHASES if nixos else PHASES
    parser = argparse.ArgumentParser(
        prog="jupiter",
        description="Install Arch Linux or NixOS, whichever this is, with "
        "Hyprland, Quickshell and the Jupiter dotfiles. 1: base system, from "
        "the live ISO; 2: desktop; 3: your packages; 4: dotfiles. On Arch "
        "phases 1 and 2 run from the ISO; on NixOS phase 1 installs "
        "everything, and 2 and 3 rebuild the system from this repo. Then 3 "
        "and 4 as your user after rebooting.",
    )
    parser.add_argument(
        "phases",
        nargs="*",
        type=int,
        choices=table,
        metavar="phase",
        help="1 to 4, run in the order given (default: 1 2 on Arch's ISO, 1 "
        "on NixOS's, 3 4 otherwise)",
    )
    default = ([1] if nixos else [1, 2]) if live else [3, 4]
    phases = parser.parse_args().phases or default
    if 1 in phases and not live:
        parser.error(f"phase 1 runs from {ISO[system.name]}")
    # Built as you: Arch's AUR packages and dotfiles, NixOS's rebuild of a
    # clone in your home, which git refuses to root.
    yours = {2, 3, 4} if nixos else {3, 4}
    if os.geteuid() == 0 and not live and yours & set(phases):
        parser.error(
            f"run phases {' and '.join(map(str, sorted(yours)))} as your own "
            "user, not as root"
        )
    if yours & set(phases) and not online(live):
        sys.exit(OFFLINE.format(dir=INSTALLER_DIR.name))
    try:
        for phase in phases:
            log(f"Phase {phase}")
            table[phase]()
    except subprocess.CalledProcessError as error:
        sys.exit(f"Failed: {shlex.join(map(str, error.cmd))}")
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        if skipped:
            warn(f"Failed to install and skipped: {' '.join(skipped)}")
    if live:
        log(
            "Reboot, log in as your user and run "
            f"~/{INSTALLER_DIR.name}/bootstrap.sh for phases 3 and 4. They "
            "need the network: the Wi-Fi the live ISO was on is joined "
            "again; if it is not, connect with `nmtui` first."
        )


def online(live: bool) -> bool:
    """Whether NetworkManager has a connection, waiting up to 30 s for one
    coming up; True where there is no NetworkManager to ask."""
    if live or not shutil.which("nm-online"):
        return True
    return succeeds("nm-online", "--quiet", "--timeout=30")


if __name__ == "__main__":
    main()
