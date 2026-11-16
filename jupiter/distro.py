"""Which system the installer runs on: Arch or NixOS, live ISO or installed.

The phases do different things on each (an Arch system is built with
pacman, a NixOS one declared by the flake in nixos/), so the installer
tells them apart before anything, and refuses a system it does not know
rather than guess: phase 1 erases disks.

- The Arch ISO has /run/archiso (archiso's own mark).
- The NixOS ISO says VARIANT_ID=installer in /etc/os-release.
- Installed, /etc/os-release says ID=arch or ID=nixos.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# JUPITER_OS_RELEASE: another os-release to read, for the tests, which run
# the phases as either system on whatever machine runs them.
OS_RELEASE = Path(os.environ.get("JUPITER_OS_RELEASE") or "/etc/os-release")
ARCHISO = Path("/run/archiso")
KNOWN = {"arch", "nixos"}


@dataclass(frozen=True)
class System:
    """The system: its name (arch, nixos) and whether it is the live ISO."""

    name: str
    live: bool


def os_release(text: str) -> dict[str, str]:
    """os-release's fields, their quotes taken off (os-release(5))."""
    fields = {}
    for line in text.splitlines():
        key, equals, value = line.strip().partition("=")
        if equals and key and not key.startswith("#"):
            fields[key] = value.strip().strip("\"'")
    return fields


def detect() -> System:
    """This system, or SystemExit naming what it is instead."""
    if ARCHISO.is_dir():
        return System("arch", live=True)
    try:
        fields = os_release(OS_RELEASE.read_text())
    except OSError:
        fields = {}
    name = fields.get("ID", "")
    if name not in KNOWN:
        found = (
            fields.get("PRETTY_NAME") or name or "a system without os-release"
        )
        raise SystemExit(
            f"This is {found}: Jupiter installs on Arch Linux and NixOS only."
        )
    live = name == "nixos" and fields.get("VARIANT_ID") == "installer"
    return System(name, live)
