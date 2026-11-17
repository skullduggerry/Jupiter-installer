"""Phase 4 on Arch: the dotfiles.

The dotfiles cloned, linked into place, the shell kept as the notification
server and the first theme rendered, as on NixOS (dotfiles.py). Then what
Arch has no configuration to declare, installed as root here: their udev
rules and pacman hooks, the login screen, on an encrypted system an
unencrypted login keyring (keyring.py), a fingerprint where there is a
reader, and zsh. Last, on an encrypted system, the TPM is bound to unlock
the disk at boot, or what is still missing for it is said (tpm.py). Safe to
run again, and run again after a firmware update that asked for the
passphrase at boot.
"""

import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import dotfiles, keyring, tpm
from ..common import log, run, succeeds, warn

ZSH = Path("/usr/bin/zsh")
SUDO_PAM = Path("/etc/pam.d/sudo")
# polkit's own stack is /usr/lib/pam.d/polkit-1, which one in /etc replaces.
POLKIT_PAM = Path("/etc/pam.d/polkit-1")
POLKIT_VENDOR_PAM = Path("/usr/lib/pam.d/polkit-1")
# First in sudo's and polkit's stacks: a finger is enough, and after three
# failed matches, 10 s without a finger or with no print enrolled, the
# password is asked for as before.
FINGERPRINT = "auth       sufficient   pam_fprintd.so max-tries=3 timeout=10\n"
# The line before it had limits, which an older run put in: replaced.
OLD_FINGERPRINT = "auth       sufficient   pam_fprintd.so\n"


def main() -> None:
    """Fetch the dotfiles, link them into place and set up around them."""
    repo = dotfiles.set_up()
    _install_system(repo)
    _install_greeter(repo)
    keyring.main()
    _fingerprint()
    _use_zsh()
    tpm.main()


def _install_system(repo: Path) -> None:
    """The udev rules (a drawing tablet's pad for the shell), pacman hooks
    (desktop entries uwsm refuses, such as Nextcloud's), and root's copy of
    the login screen's installer, which the shell's Settings app runs."""
    script = repo / "scripts/install-system.sh"
    if script.exists():
        run("sudo", script)


def _install_greeter(repo: Path) -> None:
    script = repo / "scripts/install-greeter.sh"
    if not script.exists():
        return
    run("sudo", script)
    manager = Path("/etc/systemd/system/display-manager.service")
    if manager.is_symlink() and manager.readlink().name != "greetd.service":
        log(f"{manager.readlink().name} stays the display manager")
    else:
        run("sudo", "systemctl", "enable", "greetd")


def _fingerprint() -> None:
    """Where fprintd finds a reader: enroll a finger, and let sudo and
    polkit's prompts take it.

    The dotfiles' lock screen listens for a finger by itself, and their login
    screen asks for one as it opens and for Enter on an empty field; the
    login keyring, kept unencrypted (keyring.py), opens either way.
    """
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
    if "no fingers enrolled" in listed.stdout:
        answer = input(
            "Enroll a fingerprint, to log in, unlock, and for sudo and "
            "polkit? [Y/n] "
        )
        if answer.strip().lower() != "n" and not succeeds("fprintd-enroll"):
            warn("No fingerprint enrolled: run fprintd-enroll later")
    for stack, vendor in ((SUDO_PAM, None), (POLKIT_PAM, POLKIT_VENDOR_PAM)):
        _take_a_finger(stack, vendor)


def _take_a_finger(stack: Path, vendor: Path | None) -> None:
    """Put pam_fprintd first in a PAM stack, from the one in /etc or else
    the package's, keeping the old file as stack~."""
    source = stack if stack.exists() else vendor
    if source is None or not source.exists():
        return
    text = source.read_text()
    lines = text.splitlines(keepends=True)
    if OLD_FINGERPRINT in lines:
        lines[lines.index(OLD_FINGERPRINT)] = FINGERPRINT
    elif "pam_fprintd" in text:
        return
    else:
        header = 1 if lines and lines[0].startswith("#%PAM") else 0
        lines.insert(header, FINGERPRINT)
    with tempfile.NamedTemporaryFile("w", suffix=".pam") as new:
        new.write("".join(lines))
        new.flush()
        # -b keeps the old one as stack~.
        run("sudo", "install", "-b", "-m", "0644", new.name, stack)
    log(f"{stack.name} takes a fingerprint too")


def _use_zsh() -> None:
    user = pwd.getpwuid(os.getuid())
    if ZSH.exists() and user.pw_shell != str(ZSH):
        run("sudo", "chsh", "--shell", ZSH, user.pw_name)
