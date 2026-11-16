"""Run the installer: python3 -m jupiter_nixos [phase ...]."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from . import dotfiles, phase1, system
from .common import INSTALLER_DIR, live, log, succeeds

PHASES = {1: phase1.main, 2: system.main, 3: dotfiles.main}
OFFLINE = (
    "No network: phases 2 and 3 download the system and the dotfiles. "
    "Connect with `nmtui` (Activate a connection, for Wi-Fi), then run "
    "~/{dir}/bootstrap.sh again."
)


def main() -> None:
    """Run the phases given on the command line."""
    parser = argparse.ArgumentParser(
        prog="jupiter_nixos",
        description="Install NixOS with Hyprland, Quickshell and the Jupiter "
        "dotfiles. 1: the system, from the NixOS ISO; 2: rebuild it from "
        "this repo (after a change, or to update); 3: the dotfiles. Phase 1 "
        "runs as root, 2 and 3 as your user after rebooting.",
    )
    parser.add_argument(
        "phases",
        nargs="*",
        type=int,
        choices=PHASES,
        metavar="phase",
        help="1 to 3, run in the order given (default: 1 on the ISO, 2 3 "
        "otherwise)",
    )
    on_iso = live()
    phases = parser.parse_args().phases or ([1] if on_iso else [2, 3])
    if os.geteuid() == 0 and {2, 3} & set(phases):
        parser.error("run phases 2 and 3 as your own user, not as root")
    if {2, 3} & set(phases) and not online(on_iso):
        sys.exit(OFFLINE.format(dir=INSTALLER_DIR.name))
    try:
        for phase in phases:
            log(f"Phase {phase}")
            PHASES[phase]()
    except subprocess.CalledProcessError as error:
        sys.exit(f"Failed: {shlex.join(map(str, error.cmd))}")
    except KeyboardInterrupt:
        sys.exit(130)
    if on_iso:
        log(
            "Reboot, log in as your user and run "
            f"~/{INSTALLER_DIR.name}/bootstrap.sh for phases 2 and 3. They "
            "need the network: the Wi-Fi the ISO was on is joined again; if "
            "it is not, connect with `nmtui` first."
        )


def online(on_iso: bool) -> bool:
    """Whether NetworkManager has a connection, waiting up to 30 s for one
    coming up; True where there is no NetworkManager to ask."""
    if on_iso or not shutil.which("nm-online"):
        return True
    return succeeds("nm-online", "--quiet", "--timeout=30")


if __name__ == "__main__":
    main()
