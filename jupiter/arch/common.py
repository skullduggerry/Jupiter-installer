"""What Arch's phases 2 and 3 share: the package lists in arch/packages/, and
installing them with pacman or paru so that a broken package is skipped
rather than failing the rest."""

from ..common import INSTALLER_DIR, succeeds, warn

PACKAGES = INSTALLER_DIR / "arch/packages"
skipped: list[str] = []  # packages that failed to install, for the summary


def packages(name: str) -> list[str]:
    """Read arch/packages/<name>: one package per line, `#` starts a
    comment."""
    lines = (PACKAGES / name).read_text().splitlines()
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
