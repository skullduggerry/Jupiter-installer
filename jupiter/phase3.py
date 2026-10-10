"""Phase 3: your own packages, from packages/pacman.txt and packages/aur.txt.

AUR packages are installed with paru, which is built first if missing,
once you have read its PKGBUILD. paru then shows each package's PKGBUILD
for review before building it.
"""

import shutil
import tempfile
from pathlib import Path

from .common import install, log, packages, run, skip, succeeds

PARU = "https://aur.archlinux.org/paru.git"


def main() -> None:
    """Install the official packages, then the AUR ones through paru."""
    aur = packages("aur.txt")
    build_tools = ["base-devel", "git"] if aur else []
    run("sudo", "pacman", "-Syu", "--noconfirm")
    pacman = ["sudo", "pacman", "-S", "--needed", "--noconfirm"]
    install(pacman, [*build_tools, *packages("pacman.txt")])
    if aur and not (shutil.which("paru") or _build_paru()):
        skip(["paru", *aur])
        return
    for name in aur:
        install(["paru", "--sync", "--aur", "--needed"], [name])


def _build_paru() -> bool:
    makepkg = ["makepkg", "--syncdeps", "--install", "--noconfirm"]
    with tempfile.TemporaryDirectory() as build:
        if not succeeds("git", "clone", PARU, build):
            return False
        # The one PKGBUILD paru cannot show for review itself.
        log("paru's PKGBUILD, from the AUR:")
        print((Path(build) / "PKGBUILD").read_text(), flush=True)
        answer = input("Build and install paru from it? [y/N] ")
        return answer.strip().lower() == "y" and succeeds(*makepkg, cwd=build)
