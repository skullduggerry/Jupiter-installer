"""Phase 4 on NixOS: the dotfiles, as Arch's phase 4 sets them up.

Cloned into your home and linked into place, the shell's notification server
kept, the first theme rendered, as on Arch (jupiter/dotfiles.py). Then
what a configuration cannot do: the login screen's copy of your theme and
wallpaper (root's install-greeter.sh, as the Settings app runs it), a
fingerprint enrolled where there is a reader, on an encrypted system an
unencrypted login keyring (jupiter/keyring.py), and last the TPM bound to
unlock the disk at boot, or what is still missing for it (tpm.py). Safe to
run again, and run again after a firmware update that asked for the
passphrase at boot.

What Arch's phase 4 installs as root (udev rules, greetd's PAM stacks, the
finger in sudo's and polkit's, zsh as your shell) nixos/login.nix and
base.nix declare instead.
"""

import os
import pwd
import shutil
import subprocess
from pathlib import Path

from .. import dotfiles, keyring
from ..common import run, succeeds, warn
from . import tpm

# Root's copy of the login screen's installer (nixos/login.nix links it).
INSTALL_GREETER = Path(
    "/usr/local/lib/jupiter/greeter/scripts/install-greeter.sh"
)


def main() -> None:
    """Fetch the dotfiles, link them into place and set up around them."""
    repo = dotfiles.set_up()
    _install_greeter(repo)
    keyring.main()
    _enroll_finger()
    tpm.main()


def _install_greeter(repo: Path) -> None:
    """The login screen in your theme, with your wallpaper: root's copy of
    install-greeter.sh, taking the rest from your clone, as the Settings
    app's Lock Screen tab runs it. greetd itself is the system's."""
    if not INSTALL_GREETER.exists():
        warn(
            f"{INSTALL_GREETER} is missing: run phase 2 first, then this "
            "again, for the login screen to show your theme"
        )
        return
    run("sudo", INSTALL_GREETER, "--from", repo)


def _enroll_finger() -> None:
    """Where fprintd finds a reader and you have no finger enrolled, offer
    to enrol one: the login screen, the lock screen, sudo and polkit take
    it (nixos/login.nix)."""
    if shutil.which("fprintd-list") is None:
        return
    user = pwd.getpwuid(os.getuid()).pw_name
    listed = subprocess.run(
        ["fprintd-list", user],
        capture_output=True,
        text=True,
        env=os.environ | {"LC_ALL": "C"},
        check=False,
    )
    if listed.returncode != 0 or "Device at" not in listed.stdout:
        return
    if "no fingers enrolled" not in listed.stdout:
        return
    answer = input(
        "Enroll a fingerprint, to log in, unlock, and for sudo and polkit? "
        "[Y/n] "
    )
    if answer.strip().lower() != "n" and not succeeds("fprintd-enroll"):
        warn("No fingerprint enrolled: run fprintd-enroll later")
