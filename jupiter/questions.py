"""What both phase 1s ask from the live ISO, and what makes an answer valid.

Arch's (jupiter/arch/phase1.py) and NixOS's (jupiter/nixos/phase1.py) ask
the same questions in the same order; only their defaults differ.
"""

import getpass
import pwd
import re
from collections.abc import Callable

from .common import output

HOSTNAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
# The account greetd's package makes for the login screen, which keeps a
# user of that name instead: the login screen would run as them.
RESERVED = {"greeter"}


def ask(question: str, default: str, valid: Callable[[str], object]) -> str:
    """Ask until the answer, or Enter for the default, is valid."""
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    while True:
        answer = input(prompt).strip() or default
        if valid(answer):
            return answer
        print(f"{answer!r} is not a valid {question.lower()}.")


def yes(question: str, default: bool) -> bool:
    """A yes or no; Enter takes the default."""
    answer = input(question).strip().lower()
    return answer.startswith("y") if answer else default


def new_password(user: str, kind: str = "Password") -> str:
    """A password typed twice, not echoed."""
    while True:
        password = getpass.getpass(f"{kind} for {user}: ")
        if password and password == getpass.getpass("Repeat it: "):
            return password
        print(f"The {kind.lower()}s were empty or did not match.")


def is_new_user(name: str) -> bool:
    """A valid user name the live system does not have already."""
    taken = {entry.pw_name for entry in pwd.getpwall()} | RESERVED
    return bool(USERNAME.fullmatch(name)) and name not in taken


def listed(*command: str) -> Callable[[str], bool]:
    """Whether an answer is one of the words a command lists."""
    return set(output(*command).split()).__contains__
