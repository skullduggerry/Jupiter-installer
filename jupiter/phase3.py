"""Phase 3: your own packages, from packages/pacman.txt and packages/aur.txt.

AUR packages are installed with paru, which is built first if missing,
once you have read its PKGBUILD. paru then shows each package's PKGBUILD
for review before building it. Where ufw is installed, KDE Connect's ports
are opened to the local networks.
"""

import shutil
import tempfile
from pathlib import Path

from .common import install, log, packages, run, skip, skipped, succeeds

PARU = "https://aur.archlinux.org/paru.git"
# The private ranges, IPv6's link-local among them: the phone finds the
# computer by broadcast and the two connect directly, so KDE Connect works on
# any local network and is never reachable from the internet.
LOCAL_NETWORKS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fe80::/10"]


def main() -> None:
    """Install the official packages, then the AUR ones through paru."""
    aur = packages("aur.txt")
    build_tools = ["base-devel", "git"] if aur else []
    run("sudo", "pacman", "-Syu", "--noconfirm")
    pacman = ["sudo", "pacman", "-S", "--needed", "--noconfirm"]
    install(pacman, [*build_tools, *packages("pacman.txt")])
    _open_kdeconnect()
    if aur and not (shutil.which("paru") or _build_paru()):
        skip(["paru", *aur])
        return
    for name in aur:
        install(["paru", "--sync", "--aur", "--needed"], [name])


def _open_kdeconnect() -> None:
    """Let KDE Connect through ufw, by the profile its package ships."""
    if "kdeconnect" not in packages("pacman.txt") or "kdeconnect" in skipped:
        return
    if not shutil.which("ufw"):
        return
    for network in LOCAL_NETWORKS:
        rule = ["from", network, "to", "any", "app", "KDEConnect"]
        run("sudo", "ufw", "allow", *rule)


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
