"""Phase 4: the dotfiles.

Clones them into your home, links every folder of their .config/ into
~/.config/ and .config/.zshrc to ~/.zshrc, then sets up what they expect
around them: the shell's notification server, the first theme, their udev
rules and pacman hooks, the login screen, a KDE Connect command that updates
them, a fingerprint where there is a reader, and zsh. Whatever a link would
replace is moved to ~/.dotfiles-backup/<time>/. Safe to run again.
"""

import json
import os
import pwd
import re
import shlex
import shutil
import string
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
KDECONNECT = CONFIG / "kdeconnect"
# The Run Command's key among KDE Connect's, its own so that running again
# replaces it rather than adding another.
UPDATE_KEY = "jupiter_update_dotfiles"
# uwsm starts KDE Connect from its XDG autostart entry, and it reads its
# commands only when it starts.
KDECONNECT_UNIT = "app-org.kde.kdeconnect.daemon@autostart.service"


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
    _offer_update(repo)
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


def _offer_update(repo: Path) -> None:
    """Let each paired KDE Connect device update the dotfiles: its Run
    Command "Update dotfiles" pulls them, which is all an update takes, as
    ~/.config links into the clone. KDE Connect keeps commands per device,
    so one paired later gets it when this runs again."""
    trusted = KDECONNECT / "trusted_devices"
    if not trusted.exists():
        return
    command = f"git -C {shlex.quote(str(repo))} pull --ff-only"
    entry = {"command": command, "name": "Update dotfiles"}
    devices = re.findall(r"^\[(\w+)\]$", trusted.read_text(), re.MULTILINE)
    added = False
    for device in devices:
        config = KDECONNECT / device / "kdeconnect_runcommand/config"
        added |= _add_command(config, entry)
    if added:
        run("systemctl", "--user", "try-restart", KDECONNECT_UNIT)


def _add_command(config: Path, entry: dict[str, str]) -> bool:
    """Put entry among the commands in config, a QSettings file that holds
    them as JSON, and tell whether that changed it. A file it cannot read
    is left alone."""
    lines = config.read_text().splitlines() if config.exists() else []
    found = [i for i, line in enumerate(lines) if line.startswith("commands=")]
    commands = {}
    if found:
        try:
            value = lines[found[0]].removeprefix("commands=")
            commands = json.loads(_from_ini(value))
            if not isinstance(commands, dict):
                raise ValueError(commands)
        except ValueError:
            warn(f"{config} is not as KDE Connect writes it: left alone")
            return False
    if commands.get(UPDATE_KEY) == entry:
        return False
    commands[UPDATE_KEY] = entry
    value = json.dumps(commands, separators=(",", ":"), ensure_ascii=False)
    line = f"commands={_to_ini(value)}"
    if found:
        lines[found[0]] = line
    else:
        if "[General]" not in lines:
            lines.insert(0, "[General]")
        lines.insert(lines.index("[General]") + 1, line)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(lines) + "\n")
    log(f"KDE Connect: {config.parent.parent.name} can update the dotfiles")
    return True


def _from_ini(value: str) -> str:
    """The text in a value QSettings wrote as "@ByteArray(...)": \\ and \\"
    escaped, and any other byte outside printable ASCII as \\x and as many
    hex digits as follow."""
    match = re.fullmatch(r'"@ByteArray\((.*)\)"', value, re.DOTALL)
    if match is None:
        raise ValueError(value)
    raw = bytearray()
    for byte, escaped, plain in re.findall(
        r"\\x([0-9a-fA-F]+)|\\(.)|(.)", match[1], re.DOTALL
    ):
        if byte:
            raw.append(int(byte, 16))  # past 255, ValueError
        elif escaped in ('"', "\\"):
            raw += escaped.encode()
        elif escaped:
            raise ValueError(escaped)
        else:
            raw += plain.encode()
    return raw.decode()


def _to_ini(text: str) -> str:
    """text as QSettings writes a byte array, the reverse of _from_ini. A
    hex digit right after a \\x escape is escaped too, or it would join
    it."""
    out = []
    after_hex = False
    for byte in text.encode():
        char = chr(byte)
        if char in '"\\':
            out.append("\\" + char)
            after_hex = False
        elif 32 <= byte < 127 and not (after_hex and char in string.hexdigits):
            out.append(char)
            after_hex = False
        else:
            out.append(f"\\x{byte:02x}")
            after_hex = True
    return '"@ByteArray(' + "".join(out) + ')"'


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
