"""Phase 4: the dotfiles.

Clones them into your home, links every folder of their .config/ into
~/.config/ and .config/.zshrc to ~/.zshrc, then sets up what they expect
around them: the shell's notification server, the first theme, the login
screen and zsh. Whatever a link would replace is moved to
~/.dotfiles-backup/<time>/. Safe to run again.
"""

import os
import pwd
import shutil
import time
from pathlib import Path

from .common import log, run, warn
from .config import DOTFILES_PUSH_URL, DOTFILES_REPO

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
ZSH = Path("/usr/bin/zsh")
NOTIFICATION_DAEMONS = ["dunst.service", "mako.service", "swaync.service"]


def main() -> None:
    """Fetch the dotfiles, link them into place and set up around them."""
    repo = HOME / Path(DOTFILES_REPO).stem
    _fetch(repo)
    _link_all(repo)
    # A daemon D-Bus starts on demand would take the shell's notifications.
    run("systemctl", "--user", "mask", *NOTIFICATION_DAEMONS)
    _render_theme(repo)
    _install_greeter(repo)
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


def _use_zsh() -> None:
    user = pwd.getpwuid(os.getuid())
    if ZSH.exists() and user.pw_shell != str(ZSH):
        run("sudo", "chsh", "--shell", ZSH, user.pw_name)
