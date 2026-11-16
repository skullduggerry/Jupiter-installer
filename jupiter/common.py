"""What the phases share: running commands, logging and package lists."""

import subprocess
from pathlib import Path

INSTALLER_DIR = Path(__file__).resolve().parent.parent
LIVE = Path("/run/archiso").is_dir()
skipped: list[str] = []  # packages that failed to install, for the summary


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


def packages(name: str) -> list[str]:
    """Read packages/<name>: one package per line, `#` starts a comment."""
    lines = (INSTALLER_DIR / "packages" / name).read_text().splitlines()
    return [word for line in lines if (word := line.split("#", 1)[0].strip())]


def install(command: list[str], names: list[str]) -> None:
    """Install packages with command, skipping those that fail.

    A broken package fails the whole transaction, so when installing them
    together fails, each is tried on its own.
    """
    if not names or succeeds(*command, *names):
        return
    broken = names
    if len(names) > 1:
        broken = [name for name in names if not succeeds(*command, name)]
    skip(broken)


def skip(names: list[str]) -> None:
    """Leave packages out, saying so now and in the summary."""
    if names:
        warn(f"Failed to install, skipping: {' '.join(names)}")
        skipped.extend(names)
