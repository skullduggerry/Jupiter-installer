"""Phase 3: the dotfiles, as the Arch installer's phase 4 sets them up.

Clones them into your home, links every folder of their .config/ into
~/.config/ and .config/.zshrc to ~/.zshrc, then sets up what they expect
around them that a configuration cannot: the shell's notification server
(the daemons D-Bus would start masked for you), the first theme, the login
screen's copy of your theme and wallpaper (root's install-greeter.sh, as the
Settings app runs it), a fingerprint enrolled where there is a reader, on an
encrypted system an unencrypted login keyring (keyring.py), and last the
TPM bound to unlock the disk at boot, or what is still missing for it
(tpm.py). Whatever a link would replace is moved to
~/.dotfiles-backup/<time>/. Safe to run again, and run again after a
firmware update that asked for the passphrase at boot.

What the Arch phase 4 installs as root (udev rules, greetd's PAM stacks,
the finger in sudo's and polkit's, zsh as your shell) nixos/login.nix and
base.nix declare instead.
"""

import os
import pwd
import shutil
import subprocess
import time
from pathlib import Path

from . import keyring, tpm
from .common import log, run, succeeds, warn
from .config import DOTFILES_PUSH_URL, DOTFILES_REPO

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
NOTIFICATION_DAEMONS = ["dunst.service", "mako.service", "swaync.service"]
# Root's copy of the login screen's installer (nixos/login.nix links it).
INSTALL_GREETER = Path(
    "/usr/local/lib/jupiter/greeter/scripts/install-greeter.sh"
)


def main() -> None:
    """Fetch the dotfiles, link them into place and set up around them."""
    repo = HOME / Path(DOTFILES_REPO).stem
    _fetch(repo)
    _link_all(repo)
    # A daemon D-Bus starts on demand would take the shell's notifications.
    run("systemctl", "--user", "mask", *NOTIFICATION_DAEMONS)
    _render_theme(repo)
    _install_greeter(repo)
    keyring.main()
    _enroll_finger()
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
