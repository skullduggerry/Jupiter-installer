"""Phase 1 on NixOS: install NixOS from the installation ISO.

The questions and the disks are the same as on Arch (jupiter/questions.py,
jupiter/disks.py): GPT with a 1 GiB EFI system partition at /boot, Btrfs
subvolumes for everything else (@nix where Arch has pacman's cache), on
LUKS2 unless you decline it, and other empty disks as encrypted data disks
if you choose them, each opened by a key file on the system. A disk you do
not choose is never written to or opened.

What Arch's phase 1 then does with pacstrap and arch-chroot, and its phases
2 and 3 with pacman, the flake declares (nixos/): this phase writes what it
asked and found to hosts/<hostname>/settings.json, nixos-generate-config's
hardware configuration beside it, both in the copy of this repo it leaves in
your home, and runs nixos-install from that copy. Passwords are set
afterwards with chpasswd, never in the configuration, which lands in the
world-readable store. Encrypted, Secure Boot keys of the system's own are
made first, for lanzaboote to sign with, and enrolled where the firmware
lets them be. The Wi-Fi networks the ISO joined (NetworkManager's) are
joined by the new system too.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import disks, questions, secureboot
from ..common import INSTALLER_DIR, graphics_cards, output, run, warn
from ..distro import OS_RELEASE
from .common import write_settings

# NetworkManager's saved networks, on the ISO and on the system alike.
NM_CONNECTIONS = Path("etc/NetworkManager/system-connections")
ISO_CONNECTIONS = Path("/") / NM_CONNECTIONS
# tzdata's table of zones and their countries, as NixOS links it.
ZONE_TAB = Path("/etc/zoneinfo/zone.tab")
SUBVOLUMES = {
    "@": "",
    "@home": "home",
    "@log": "var/log",
    "@nix": "nix",
}
# sbctl's keys, where lanzaboote's pkiBundle (nixos/secureboot.nix) finds
# them; sbctl is not on the ISO, so it comes from nixpkgs for the one call.
SBCTL = Path("var/lib/sbctl")
NIX = ["nix", "--extra-experimental-features", "nix-command flakes"]
GRAPHICS = {"0x8086": "intel", "0x1002": "amd", "0x10de": "nouveau"}
LOCALE = re.compile(r"[a-z]{2,3}_[A-Z]{2}(@[a-z]+)?\.UTF-8")


def main() -> None:
    """Install NixOS on a disk of your choice and make it bootable."""
    if not disks.EFI.is_dir():
        raise SystemExit("Boot the ISO in UEFI mode to install.")
    if disks.MNT.is_mount():
        run("umount", "--recursive", disks.MNT)

    keymaps = questions.listed("localectl", "list-keymaps")
    keymap = questions.ask("Keymap", "us", keymaps)
    # The console's own, for the passwords below: as typed at boot. Not a
    # console (over SSH, a serial line), characters arrive as they are.
    subprocess.run(["loadkeys", keymap], check=False, capture_output=True)
    firmware = secureboot.state(disks.EFI / "efivars")
    if firmware == "none":
        print(secureboot.NO_SECURE_BOOT_HELP)
    elif firmware != "setup":
        print(secureboot.SETUP_MODE_HELP)
    devices = disks.close_leftovers(disks.devices())
    disk = disks.choose_disk(devices)
    encrypt = questions.yes(f"Encrypt {disk}? [Y/n] ", default=True)
    passphrase = (
        questions.new_password("the disk", "Passphrase") if encrypt else ""
    )
    data = disks.choose_data_disks(devices, disk) if encrypt else []
    hostname = questions.ask("Hostname", "nixos", questions.HOSTNAME.fullmatch)
    user = questions.ask("Username", "", questions.is_new_user)
    passwords = {
        user: questions.new_password(user),
        "root": questions.new_password("root"),
    }
    zones = questions.listed("timedatectl", "list-timezones")
    timezone = questions.ask("Time zone", "UTC", zones)
    locale = questions.ask("Locale", "en_US.UTF-8", LOCALE.fullmatch)
    if not questions.yes(f"Erase everything on {disk}? [y/N] ", default=False):
        raise SystemExit("Nothing was changed.")

    esp, root = disks.partition(disk)
    luks = (
        disks.encrypt(root, disks.ROOT_VOLUME, passphrase) if encrypt else None
    )
    if luks:
        root = f"/dev/mapper/{disks.ROOT_VOLUME}"
    filesystem = disks.make_system(esp, root, SUBVOLUMES)
    volumes = []
    for volume in data:
        data_luks, data_filesystem = disks.make_data_disk(volume, passphrase)
        volumes.append(
            {
                "name": volume.name,
                "mount": volume.mount,
                "luks": data_luks,
                "filesystem": data_filesystem,
            }
        )
    settings = {
        "hostname": hostname,
        "user": user,
        "timezone": timezone,
        "country": questions.country(timezone, ZONE_TAB.read_text()),
        "locale": locale,
        "keymap": keymap,
        "xkb": questions.keyboard(keymap, _kbd_model_map().read_text()),
        "esp": _uuid(esp),
        "root": {"luks": luks, "filesystem": filesystem},
        "data": volumes,
        "gpus": gpus(),
        "tpm": False,
        "volumeKey": None,
        "stateVersion": _release(),
    }
    copy = _copy_installer(user)
    folder = copy / "hosts" / hostname
    write_settings(folder, settings)
    hardware = output(
        "nixos-generate-config", "--root", disks.MNT, "--no-filesystems",
        "--show-hardware-config",
    )  # fmt: skip
    (folder / "hardware-configuration.nix").write_text(hardware)
    # A flake in a git repo sees tracked files alone.
    run("git", "-C", copy, "add", "--", f"hosts/{hostname}")
    _carry_wifi()
    if encrypt:
        _create_keys(copy)
    run(
        "nixos-install", "--root", disks.MNT, "--no-root-passwd",
        "--no-channel-copy", "--flake", f"{copy}#{hostname}",
    )  # fmt: skip
    logins = [f"{name}:{password}" for name, password in passwords.items()]
    _enter("chpasswd", data="\n".join(logins) + "\n")
    _enter("chown", "--recursive", f"{user}:", f"/home/{user}")
    for volume in data:
        _own(volume, user)
    if encrypt:
        _enroll_keys(firmware)


def _own(volume: disks.DataDisk, user: str) -> None:
    """Mount a data disk where it goes and give its top folder to the user."""
    run(
        "mount", "--mkdir", "-o", "compress=zstd",
        f"/dev/mapper/{volume.name}", disks.MNT / volume.mount.lstrip("/"),
    )  # fmt: skip
    _enter("chown", f"{user}:", volume.mount)


def _uuid(partition: str) -> str:
    blkid = ["blkid", "--match-tag", "UUID", "--output", "value", partition]
    return output(*blkid).strip()


def _kbd_model_map() -> Path:
    """systemd's table of console keymaps and their X layouts, beside the
    localectl that reads it."""
    localectl = shutil.which("localectl")
    if localectl is None:
        raise SystemExit("localectl is missing: this is not the NixOS ISO.")
    share = Path(localectl).resolve().parent.parent / "share"
    return share / "systemd/kbd-model-map"


def gpus(root: Path = Path("/")) -> list[str]:
    """The driver for each GPU: nvidia for NVIDIA's from Turing on, which
    nvidia-open supports, Mesa's (intel, amd, nouveau) for the rest."""
    found = {
        "nvidia" if nvidia_open else GRAPHICS[vendor]
        for vendor, nvidia_open in graphics_cards(root)
        if nvidia_open or vendor in GRAPHICS
    }
    return sorted(found)


def _release() -> str:
    """The NixOS release of the ISO, which the system is installed with."""
    text = OS_RELEASE.read_text()
    found = re.search(r'^VERSION_ID="?([0-9.]+)', text, re.MULTILINE)
    if not found:
        raise SystemExit("The ISO's /etc/os-release names no NixOS release.")
    return found.group(1)


def _carry_wifi() -> None:
    """Copy NetworkManager's saved connections from the ISO (nmtui's), so
    the new system joins the same networks after the reboot."""
    if not ISO_CONNECTIONS.is_dir():
        return
    folder = disks.MNT / NM_CONNECTIONS
    for saved in sorted(ISO_CONNECTIONS.glob("*.nmconnection")):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = folder / saved.name
        # Created 0600, root's, as NetworkManager insists, then filled.
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb"
        ) as file:
            file.write(saved.read_bytes())


def _copy_installer(user: str) -> Path:
    """Leave this repo in the new home, git history and all: the flake is
    built from it, and phases 2 and 3 run from it."""
    copy = disks.MNT / "home" / user / INSTALLER_DIR.name
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(INSTALLER_DIR, copy, ignore=ignore, symlinks=True)
    return copy


def _create_keys(flake: Path) -> None:
    """Secure Boot keys of the new system's own, made before nixos-install,
    whose lanzaboote signs systemd-boot and the kernel images with them.

    sbctl is the flake's (its locked nixpkgs), the one the system gets.
    Without Landlock: sbctl 0.18 confines create-keys to its default
    /var/lib before it reads --export and --database-path, which would
    refuse /mnt/var/lib/sbctl (cmd/sbctl/create-keys.go).
    """
    keys = disks.MNT / SBCTL
    keys.mkdir(mode=0o700, parents=True, exist_ok=True)
    run(
        *NIX, "shell", "--inputs-from", flake, "nixpkgs#sbctl", "--command",
        "sbctl", "--disable-landlock", "create-keys",
        "--database-path", keys / "GUID", "--export", keys / "keys",
    )  # fmt: skip


def _enroll_keys(firmware: str) -> None:
    """Enrol the keys, Microsoft's and the firmware's own beside them
    (secureboot.enroll), if the firmware lets them be: in Setup Mode."""
    if firmware != "setup":
        return
    if not secureboot.enroll("nixos-enter", "--root", disks.MNT, "--"):
        warn("Could not enrol the Secure Boot keys: phase 4 says what is left")


def _enter(*command: str, data: str | None = None) -> None:
    run("nixos-enter", "--root", disks.MNT, "--", *command, data=data)
