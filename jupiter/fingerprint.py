"""A fingerprint, enrolled in phase 4 where fprintd finds a reader and you
have none: the login screen, the lock screen, sudo and polkit then take it.

Which PAM stacks take a finger is each system's: Arch's phase 4 puts
pam_fprintd in sudo's and polkit's (jupiter/arch/phase4.py), NixOS declares
the same (nixos/login.nix).
"""

import os
import pwd
import shutil
import subprocess

from .common import succeeds, warn

QUESTION = (
    "Enroll a fingerprint, to log in, unlock, and for sudo and polkit? [Y/n] "
)


def enroll() -> bool:
    """Offer to enrol a finger where there is a reader and none is
    enrolled; True where there is a reader."""
    if shutil.which("fprintd-list") is None:
        return False
    user = pwd.getpwuid(os.getuid()).pw_name
    listed = subprocess.run(
        ["fprintd-list", user],
        capture_output=True,
        text=True,
        env=os.environ | {"LC_ALL": "C"},  # its words, not a translation
        check=False,
    )
    if listed.returncode != 0 or "Device at" not in listed.stdout:
        return False
    if "no fingers enrolled" in listed.stdout:
        answer = input(QUESTION)
        if answer.strip().lower() != "n" and not succeeds("fprintd-enroll"):
            warn("No fingerprint enrolled: run fprintd-enroll later")
    return True
