"""The login keyring, kept unencrypted: phase 4's step for gnome-keyring.

A finger at the login screen gives gnome-keyring no password to unlock the
login keyring with, so on an encrypted system (its root on LUKS) it is kept
unencrypted, and opens however you logged in. Where there is none yet, an
empty one is made. An unencrypted system keeps its keyring as it is, and
gets none made: its secrets would lie on the disk in the clear.

Where an encrypted one exists, its secrets (an app's sign-in, Nextcloud's
app password) are kept: asked first, gnome-keyring's own dialog changes its
password (the one Seahorse's "Change Password" shows), and you leave the new
one empty; a copy of the old file is put beside it. No password passes
through the installer, and a keyring is never written over or deleted.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

from . import tpm
from .common import log, output, run, warn

PLAIN = """\
[keyring]
display-name=login
ctime=0
mtime=0
lock-on-idle=false
lock-after=false
"""
ENCRYPTED_MAGIC = b"GnomeKeyring\n\r\0\n"
SECRETS = "org.freedesktop.secrets"
SERVICE = "/org/freedesktop/secrets"
LOGIN = "/org/freedesktop/secrets/collection/login"
# gnome-keyring's own interface for changing a keyring's password, which
# Seahorse uses: it asks through gnome-keyring's dialog.
INTERNAL = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"
PROMPT = "org.freedesktop.Secret.Prompt"
DIALOG_HELP = """\
gnome-keyring now asks, in a dialog, for the keyring's current password (your
login password), then for a new one: leave the new one empty, and confirm
storing the keyring unencrypted."""


def folder() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share"
    return Path(data) / "keyrings"


def main() -> None:
    """Make the login keyring unencrypted, keeping what it holds, where the
    disk under it is encrypted."""
    if tpm.root_volume() is None:
        log(
            "The disk is not encrypted: the login keyring stays as it is, "
            "opened by the password (a finger at the login screen leaves it "
            "locked)"
        )
        return
    keyrings = folder()
    login = keyrings / "login.keyring"
    if not login.exists():
        _create(keyrings)
        log("Made an unencrypted login keyring: any login opens it")
        return
    if login.read_bytes().startswith(b"[keyring]"):
        return
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get(
        "DBUS_SESSION_BUS_ADDRESS"
    ):
        warn(
            "Your login keyring is encrypted with your password, which a "
            "finger at the login screen cannot open: run bootstrap.sh 4 "
            "from the desktop to store it unencrypted"
        )
        return
    question = (
        "Your login keyring is encrypted with your login password, which a "
        "finger at the login screen does not give it. Store it unencrypted "
        "on the encrypted disk, keeping its secrets? [Y/n] "
    )
    if input(question).strip().lower().startswith("n"):
        return
    copy = login.with_name(f"login.keyring.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(login, copy)
    print(DIALOG_HELP, flush=True)
    _change_password()
    if login.read_bytes().startswith(b"[keyring]"):
        log(f"The login keyring is unencrypted; the encrypted one is {copy}")
        return
    copy.unlink()
    warn(
        "The login keyring is still encrypted (the dialog was cancelled, or "
        "a new password given): run bootstrap.sh 4 again to try again"
    )


def _change_password() -> None:
    """gnome-keyring's dialog for the login keyring's password, waited for
    until it is answered or dismissed."""
    gdbus = ["gdbus", "call", "--session", "--dest", SECRETS]
    reply = output(
        *gdbus, "--object-path", SERVICE,
        "--method", f"{INTERNAL}.ChangeWithPrompt", LOGIN,
    )  # fmt: skip
    prompt = reply.split("'")[1]  # (objectpath '/org/.../prompt/p1',)
    monitor = ["gdbus", "monitor", "--session", "--dest", SECRETS]
    with subprocess.Popen(
        [*monitor, "--object-path", prompt],
        stdout=subprocess.PIPE,
        text=True,
    ) as watching:
        assert watching.stdout
        try:
            run(
                *gdbus, "--object-path", prompt,
                "--method", f"{PROMPT}.Prompt", "",
            )  # fmt: skip
            for line in watching.stdout:
                if f"{PROMPT}.Completed" in line:
                    break
        finally:
            watching.terminate()


def _create(keyrings: Path) -> None:
    keyrings.mkdir(mode=0o700, parents=True, exist_ok=True)
    login = keyrings / "login.keyring"
    # O_EXCL: never over a keyring that appeared meanwhile.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(login, flags, 0o600), "w") as file:
        file.write(PLAIN)
    default = keyrings / "default"
    if not default.exists():
        default.write_text("login")
        default.chmod(0o600)
