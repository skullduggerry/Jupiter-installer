"""Phase 3: your own packages, from packages/pacman.txt and packages/aur.txt.

AUR packages are installed with paru, which is built first if missing,
once you have read its PKGBUILD. paru then shows each package's PKGBUILD
for review before building it. A package only [multilib] has (steam) gets
[multilib] enabled in /etc/pacman.conf first. Where ufw is installed, KDE
Connect's ports are opened to the local networks; turning ufw on is yours
(`sudo ufw enable`).
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import (
    install,
    log,
    output,
    packages,
    run,
    skip,
    skipped,
    succeeds,
)

PARU = "https://aur.archlinux.org/paru.git"
PACMAN_CONF = Path("/etc/pacman.conf")
# The 32-bit drivers of the graphics drivers phase 1 installs.
LIB32 = {
    "mesa": "lib32-mesa",
    "vulkan-radeon": "lib32-vulkan-radeon",
    "vulkan-intel": "lib32-vulkan-intel",
    "vulkan-nouveau": "lib32-vulkan-nouveau",
    "nvidia-utils": "lib32-nvidia-utils",
}
# Arch's pacman.conf ships [multilib] commented out.
MULTILIB_OFF = re.compile(
    r"^#\[multilib\]\n#(Include = /etc/pacman\.d/mirrorlist)$", re.MULTILINE
)
# The private ranges, IPv6's link-local among them: the phone finds the
# computer by broadcast and the two connect directly, so KDE Connect works on
# any local network and is never reachable from the internet.
LOCAL_NETWORKS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fe80::/10"]


def main() -> None:
    """Install the official packages, then the AUR ones through paru."""
    aur = packages("aur.txt")
    build_tools = ["base-devel", "git"] if aur else []
    run("sudo", "pacman", "-Syu", "--noconfirm")
    _multilib(packages("pacman.txt"))
    lib32 = _lib32_drivers(packages("pacman.txt"))
    pacman = ["sudo", "pacman", "-S", "--needed", "--noconfirm"]
    install(pacman, [*build_tools, *lib32, *packages("pacman.txt")])
    _open_kdeconnect()
    if aur and not (shutil.which("paru") or _build_paru()):
        skip(["paru", *aur])
        return
    for name in aur:
        install(["paru", "--sync", "--aur", "--needed"], [name])


def _multilib(names: list[str]) -> None:
    """Enable [multilib] where a listed package is in no enabled repository
    and pacman.conf has it commented out, as a fresh install does."""
    known = set(output("pacman", "-Slq").split())
    unknown = [name for name in names if name not in known]
    text = PACMAN_CONF.read_text()
    if not unknown or not MULTILIB_OFF.search(text):
        return
    enabled = MULTILIB_OFF.sub(r"[multilib]\n\1", text)
    with tempfile.NamedTemporaryFile("w", suffix=".conf") as new:
        new.write(enabled)
        new.flush()
        # -b keeps the old one as pacman.conf~.
        run("sudo", "install", "-b", "-m", "0644", new.name, PACMAN_CONF)
    # All repositories at once: a bare -Sy would make a partial upgrade.
    run("sudo", "pacman", "-Syu", "--noconfirm")
    log(f"Enabled [multilib] in {PACMAN_CONF}, for {' '.join(unknown)}")


def _lib32_drivers(names: list[str]) -> list[str]:
    """Where a listed package comes from [multilib] (steam): the 32-bit
    drivers of the graphics drivers installed. Without them pacman's
    --noconfirm takes the first provider of lib32-vulkan-driver, NVIDIA's,
    whatever the machine's card."""
    listed = subprocess.run(
        ["pacman", "-Slq", "multilib"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode or not set(listed.stdout.split()) & set(names):
        return []
    installed = set(output("pacman", "-Qq").split())
    return [lib32 for name, lib32 in LIB32.items() if name in installed]


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
