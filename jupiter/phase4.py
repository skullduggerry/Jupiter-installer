"""Phase 4: the dotfiles.

Clones them into your home, links every folder of their .config/ into
~/.config/ and .config/.zshrc to ~/.zshrc, then sets up what they expect
around them: the shell's notification server, the first theme, their udev
rules and pacman hooks, the login screen, on an encrypted system an
unencrypted login keyring (keyring.py), a fingerprint where there is a
reader, and zsh. Whatever a link would replace is moved to
~/.dotfiles-backup/<time>/. Last, on an encrypted system, the TPM is bound
to unlock the disk at boot, or what is still missing for it is said
(tpm.py). Safe to run again, and run again after a firmware update that
asked for the passphrase at boot.
"""

import os
import pwd
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import keyring, tpm
from .common import log, run, succeeds, warn
from .config import DOTFILES_PUSH_URL, DOTFILES_REPO

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
ZSH = Path("/usr/bin/zsh")
NOTIFICATION_DAEMONS = ["dunst.service", "mako.service", "swaync.service"]
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
    repo = HOME / Path(DOTFILES_REPO).stem
    _fetch(repo)
    _link_all(repo)
    # A daemon D-Bus starts on demand would take the shell's notifications.
    run("systemctl", "--user", "mask", *NOTIFICATION_DAEMONS)
    _render_theme(repo)
    _install_system(repo)
    _install_greeter(repo)
    keyring.main()
    _fingerprint()
    _use_zsh()
    tpm.main()


def _fetch(repo: Path) -> None:
    if (repo / ".git").is_dir():
        # Offline, or a clone with commits its origin lacks: the rest of the
        # phase sets up the clone that is there.
        if not succeeds("git", "-C", repo, "pull", "--ff-only"):
            warn(f"Could not update {repo}: setting it up as it is")
    else:
        run("git", "clone", DOTFILES_REPO, repo)
    if DOTFILES_PUSH_URL:
        push = ["remote", "set-url", "--push", "origin", DOTFILES_PUSH_URL]
        run("git", "-C", repo, *push)


def _link_all(repo: Path) -> None:
    backup = HOME / ".dotfiles-backup" / time.strftime("%Y%m%d-%H%M%S")
    links = {
        CONFIG / entry.name: entry
        for entry in (repo / ".config").iterdir()
        if not entry.name.startswith(".")
    }
    if (zshrc := repo / ".config/.zshrc").exists():
        links[HOME / ".zshrc"] = zshrc
    for target, source in links.items():
        _link(source, target, backup)
    for target in CONFIG.iterdir():
        if (
            target.is_symlink()
            and not target.exists()
            and target.readlink().is_relative_to(repo)
        ):
            target.unlink()
            log(f"Removed {target}, the dotfiles no longer have its folder")


def _link(source: Path, target: Path, backup: Path) -> None:
    if target.is_symlink() and target.readlink() == source:
        return
    if target.exists() or target.is_symlink():
        # Under the backup as under the home; by its whole path where
        # XDG_CONFIG_HOME is outside it.
        base = HOME if target.is_relative_to(HOME) else Path(target.anchor)
        moved = backup / target.relative_to(base)
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(target, moved)
        log(f"Moved {target} to {moved}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    log(f"Linked {target}")


def _render_theme(repo: Path) -> None:
    """Render the colour files now, rather than at the first login."""
    if shutil.which("wallust"):
        run(repo / ".config/wallust/apply.sh")
    else:
        warn(
            "wallust is missing: the first login after installing it "
            "renders the theme"
        )


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
