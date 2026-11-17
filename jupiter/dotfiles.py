"""The dotfiles in your home, the start of both phase 4s: cloned (or pulled),
every folder of their .config/ linked into ~/.config/ and .config/.zshrc to
~/.zshrc, the shell kept as the notification server, and the first theme
rendered. Whatever a link would replace is moved to
~/.dotfiles-backup/<time>/.

What each system then sets up around them is its own phase 4's: Arch's
installs the root files (jupiter/arch/phase4.py), NixOS's flake declares
them (jupiter/nixos/phase4.py).
"""

import os
import shutil
import time
from pathlib import Path

from .common import log, run, succeeds, warn
from .config import DOTFILES_PUSH_URL, DOTFILES_REPO

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
NOTIFICATION_DAEMONS = ["dunst.service", "mako.service", "swaync.service"]


def set_up() -> Path:
    """Fetch the dotfiles, link them into place, keep the shell's
    notifications and render the theme; returns the clone."""
    repo = HOME / Path(DOTFILES_REPO).stem
    fetch(repo)
    link_all(repo)
    # A daemon D-Bus starts on demand would take the shell's notifications.
    run("systemctl", "--user", "mask", *NOTIFICATION_DAEMONS)
    render_theme(repo)
    return repo


def fetch(repo: Path) -> None:
    """Clone the dotfiles, or bring the clone up to date."""
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


def link_all(repo: Path) -> None:
    """Link every folder of .config/ and .zshrc; drop links to folders the
    dotfiles no longer have."""
    backup = HOME / ".dotfiles-backup" / time.strftime("%Y%m%d-%H%M%S")
    links = {
        CONFIG / entry.name: entry
        for entry in (repo / ".config").iterdir()
        if not entry.name.startswith(".")
    }
    if (zshrc := repo / ".config/.zshrc").exists():
        links[HOME / ".zshrc"] = zshrc
    for target, source in links.items():
        link(source, target, backup)
    for target in CONFIG.iterdir():
        if (
            target.is_symlink()
            and not target.exists()
            and target.readlink().is_relative_to(repo)
        ):
            target.unlink()
            log(f"Removed {target}, the dotfiles no longer have its folder")


def link(source: Path, target: Path, backup: Path) -> None:
    """Link target to source, moving what was there under backup."""
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


def render_theme(repo: Path) -> None:
    """Render the colour files now, rather than at the first login."""
    if shutil.which("wallust"):
        run(repo / ".config/wallust/apply.sh")
    else:
        warn(
            "wallust is missing: the first login after installing it "
            "renders the theme"
        )
