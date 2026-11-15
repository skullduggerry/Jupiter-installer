"""Run the installer: python3 -m jupiter [phase ...]."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from . import phase1, phase2, phase3, phase4
from .common import INSTALLER_DIR, LIVE, log, skipped, succeeds, warn

PHASES = {1: phase1.main, 2: phase2.main, 3: phase3.main, 4: phase4.main}
OFFLINE = (
    "No network: phases 3 and 4 download packages and the dotfiles. Connect "
    "with `nmtui` (Activate a connection, for Wi-Fi), then run "
    "~/{dir}/bootstrap.sh again."
)


def main() -> None:
    """Run the phases given on the command line."""
    parser = argparse.ArgumentParser(
        prog="jupiter",
        description="Install Arch Linux with Hyprland, Quickshell and the "
        "Jupiter dotfiles. 1: base system, 2: desktop, 3: your packages, "
        "4: dotfiles. Phases 1 and 2 run as root from the live ISO, 3 and "
        "4 as your user after rebooting.",
    )
    parser.add_argument(
        "phases",
        nargs="*",
        type=int,
        choices=PHASES,
        metavar="phase",
        help="1 to 4, run in the order given (default: 1 2 on the live ISO, "
        "3 4 otherwise)",
    )
    phases = parser.parse_args().phases or ([1, 2] if LIVE else [3, 4])
    if os.geteuid() == 0 and {3, 4} & set(phases):
        parser.error("run phases 3 and 4 as your own user, not as root")
    if {3, 4} & set(phases) and not online():
        sys.exit(OFFLINE.format(dir=INSTALLER_DIR.name))
    try:
        for phase in phases:
            log(f"Phase {phase}")
            PHASES[phase]()
    except subprocess.CalledProcessError as error:
        sys.exit(f"Failed: {shlex.join(map(str, error.cmd))}")
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        if skipped:
            warn(f"Failed to install and skipped: {' '.join(skipped)}")
    if LIVE:
        log(
            "Reboot, log in as your user and run "
            f"~/{INSTALLER_DIR.name}/bootstrap.sh for phases 3 and 4. They "
            "need the network: the Wi-Fi the live ISO was on is joined "
            "again; if it is not, connect with `nmtui` first."
        )


def online() -> bool:
    """Whether NetworkManager has a connection, waiting up to 30 s for one
    coming up; True where there is no NetworkManager to ask."""
    if LIVE or not shutil.which("nm-online"):
        return True
    return succeeds("nm-online", "--quiet", "--timeout=30")


if __name__ == "__main__":
    main()
