"""What the phases share: running commands, logging, and the machine's
settings in hosts/."""

import json
import socket
import subprocess
from pathlib import Path
from typing import Any

INSTALLER_DIR = Path(__file__).resolve().parent.parent
HOSTS = INSTALLER_DIR / "hosts"
OS_RELEASE = Path("/etc/os-release")


def live() -> bool:
    """Whether this is the NixOS installation ISO, which says so in
    os-release (VARIANT_ID=installer)."""
    try:
        text = OS_RELEASE.read_text()
    except OSError:
        return False
    return "\nVARIANT_ID=installer\n" in f"\n{text}\n"


def log(message: str) -> None:
    """Print a progress message."""
    print(f"\033[1;34m==>\033[0m {message}", flush=True)


def warn(message: str) -> None:
    """Print a warning."""
    print(f"\033[1;33m==> WARNING:\033[0m {message}", flush=True)


def run(
    *command: str | Path, data: str | None = None, cwd: str | None = None
) -> None:
    """Run a command, feeding it data on stdin; raise if it fails."""
    subprocess.run(command, input=data, text=True, cwd=cwd, check=True)


def succeeds(*command: str | Path, cwd: str | None = None) -> bool:
    """Run a command and tell whether it succeeded."""
    return subprocess.run(command, cwd=cwd, check=False).returncode == 0


def output(*command: str | Path) -> str:
    """Run a command and return what it printed; raise if it fails."""
    return subprocess.run(
        command, capture_output=True, text=True, check=True
    ).stdout


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
