"""What the NixOS phases share: this machine's settings in hosts/, which
phase 1 writes and the flake reads (flake.nix)."""

import json
import socket
from pathlib import Path
from typing import Any

from ..common import INSTALLER_DIR

HOSTS = INSTALLER_DIR / "hosts"


def host() -> str:
    """This machine's folder in hosts/: the one whose settings name its
    hostname."""
    name = socket.gethostname()
    for settings in sorted(HOSTS.glob("*/settings.json")):
        if json.loads(settings.read_text()).get("hostname") == name:
            return settings.parent.name
    known = ", ".join(
        sorted(p.parent.name for p in HOSTS.glob("*/settings.json"))
    )
    raise SystemExit(
        f"No folder in {HOSTS} has settings for {name} (there are: "
        f"{known or 'none'}): phase 1 writes it, or copy one and change it."
    )


def read_settings(name: str) -> dict[str, Any]:
    """A machine's settings.json."""
    settings: dict[str, Any] = json.loads(
        (HOSTS / name / "settings.json").read_text()
    )
    return settings


def write_settings(folder: Path, settings: dict[str, Any]) -> None:
    """Write settings.json, which the flake reads with importJSON: JSON, so
    no answer can become Nix code."""
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    (folder / "settings.json").write_text(text)
