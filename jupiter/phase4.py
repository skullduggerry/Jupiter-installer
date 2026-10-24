"""Phase 4: the dotfiles.

Clones them into your home, links every folder of their .config/ into
~/.config/ and .config/.zshrc to ~/.zshrc, then sets up what they expect
around them: the shell's notification server, the first theme, their udev
rules and pacman hooks, the login screen, a fingerprint where there is a
reader, and zsh. Whatever a link would replace is moved to
~/.dotfiles-backup/<time>/. Safe to run again.
"""

import os
import pwd
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .common import log, run, succeeds, warn
from .config import DOTFILES_PUSH_URL, DOTFILES_REPO

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
ZSH = Path("/usr/bin/zsh")
NOTIFICATION_DAEMONS = ["dunst.service", "mako.service", "swaync.service"]
SUDO_PAM = Path("/etc/pam.d/sudo")
# First in sudo's stack: a finger is enough, and after three failed matches,
# a timeout or with no print enrolled, sudo asks for the password as before.
FINGERPRINT = "auth       sufficient   pam_fprintd.so\n"


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
    _fingerprint()
    _use_zsh()


def _fetch(repo: Path) -> None:
    if (repo / ".git").is_dir():
        run("git", "-C", repo, "pull", "--ff-only")
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
        moved = backup / target.relative_to(HOME)
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
    """The udev rules (a drawing tablet's pad for the shell) and pacman
    hooks (desktop entries uwsm refuses, such as Nextcloud's)."""
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
    """Where fprintd finds a reader: enroll a finger, and let sudo take it.

    The dotfiles' lock screen listens for a finger by itself. Logging in
    stays with the password, which is what unlocks the keyring.
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
            "Enroll a fingerprint, for the lock screen and sudo? [Y/n] "
        )
        if answer.strip().lower() != "n" and not succeeds("fprintd-enroll"):
            warn("No fingerprint enrolled: run fprintd-enroll later")
    text = SUDO_PAM.read_text()
    if "pam_fprintd" in text:
        return
    lines = text.splitlines(keepends=True)
    header = 1 if lines and lines[0].startswith("#%PAM") else 0
    lines.insert(header, FINGERPRINT)
    with tempfile.NamedTemporaryFile("w", suffix=".pam") as new:
        new.write("".join(lines))
        new.flush()
        # -b keeps the old one as sudo~.
        run("sudo", "install", "-b", "-m", "0644", new.name, SUDO_PAM)
    log("sudo takes a fingerprint too")


def _use_zsh() -> None:
    user = pwd.getpwuid(os.getuid())
    if ZSH.exists() and user.pw_shell != str(ZSH):
        run("sudo", "chsh", "--shell", ZSH, user.pw_name)
