"""What every phase, on either system, uses: running commands and logging."""

import subprocess
from pathlib import Path

INSTALLER_DIR = Path(__file__).resolve().parent.parent
LIVE = Path("/run/archiso").is_dir()  # the Arch ISO (distro.py tells NixOS's)
# NVIDIA's first GPU nvidia-open drives, by PCI device ID: older ones keep
# nouveau, on Arch (jupiter/arch/phase1.py) and NixOS
# (jupiter/nixos/phase1.py) alike.
NVIDIA_TURING = 0x1E00


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
