"""Phase 1 on NixOS: install NixOS from the installation ISO.

The disk is laid out as on Arch, by Arch's own code (jupiter/phase1.py says
how): GPT with a 1 GiB EFI system partition at /boot, Btrfs subvolumes for
everything else (@nix where Arch has pacman's cache), on LUKS2 unless you
decline it, and other empty disks as encrypted data disks if you choose
them, each opened by a key file on the system. A disk you do not choose is
never written to or opened.

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
import uuid
from pathlib import Path

from .. import phase1 as disks
from .. import secureboot
from ..common import INSTALLER_DIR, output, run, succeeds, warn
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
XKB = ("layout", "model", "variant", "options")
LOCALE = re.compile(r"[a-z]{2,3}_[A-Z]{2}(@[a-z]+)?\.UTF-8")


def main() -> None:
    """Install NixOS on a disk of your choice and make it bootable."""
    if not disks.EFI.is_dir():
        raise SystemExit("Boot the ISO in UEFI mode to install.")
    if disks.MNT.is_mount():
        run("umount", "--recursive", disks.MNT)

    keymaps = disks._listed("localectl", "list-keymaps")
    keymap = disks._ask("Keymap", "us", keymaps)
    # The console's own, for the passwords below: as typed at boot. Not a
    # console (over SSH, a serial line), characters arrive as they are.
    subprocess.run(["loadkeys", keymap], check=False, capture_output=True)
    firmware = secureboot.state(disks.EFI / "efivars")
    if firmware == "none":
        print(secureboot.NO_SECURE_BOOT_HELP)
    elif firmware != "setup":
        print(secureboot.SETUP_MODE_HELP)
    devices = disks._close_leftovers(disks._devices())
    disk = disks._choose_disk(devices)
    encrypt = disks._yes(f"Encrypt {disk}? [Y/n] ", default=True)
    passphrase = (
        disks._new_password("the disk", "Passphrase") if encrypt else ""
    )
    data = disks._choose_data_disks(devices, disk) if encrypt else []
    hostname = disks._ask("Hostname", "nixos", disks.HOSTNAME.fullmatch)
    user = disks._ask("Username", "", disks._is_new_user)
    passwords = {
        user: disks._new_password(user),
        "root": disks._new_password("root"),
    }
    zones = disks._listed("timedatectl", "list-timezones")
    timezone = disks._ask("Time zone", "UTC", zones)
    locale = disks._ask("Locale", "en_US.UTF-8", LOCALE.fullmatch)
    if not disks._yes(f"Erase everything on {disk}? [y/N] ", default=False):
        raise SystemExit("Nothing was changed.")

    esp, root = disks._partition(disk)
    luks = (
        disks._encrypt(root, disks.ROOT_VOLUME, passphrase)
        if encrypt
        else None
    )
    if luks:
        root = f"/dev/mapper/{disks.ROOT_VOLUME}"
    filesystem = _mount(esp, root)
    volumes = []
    for volume in data:
        data_luks, data_filesystem = disks._make_data_disk(volume, passphrase)
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
        "country": country(timezone, ZONE_TAB.read_text()),
        "locale": locale,
        "keymap": keymap,
        "xkb": keyboard(keymap, _kbd_model_map().read_text()),
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
        _create_keys()
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


def _mount(esp: str, root: str) -> str:
    """Format the ESP and the root, make the subvolumes and mount them all
    at /mnt; returns the Btrfs's UUID."""
    filesystem = str(uuid.uuid4())
    run("mkfs.fat", "-F", "32", esp)
    run("mkfs.btrfs", "--force", f"--uuid={filesystem}", root)
    run("mount", root, disks.MNT)
    run(
        "btrfs",
        "subvolume",
        "create",
        *(disks.MNT / name for name in SUBVOLUMES),
    )
    run("umount", disks.MNT)
    for name, path in SUBVOLUMES.items():
        options = f"compress=zstd,subvol={name}"
        run("mount", "--mkdir", "-o", options, root, disks.MNT / path)
    run(
        "mount",
        "--mkdir",
        "-o",
        "fmask=0077,dmask=0077",
        esp,
        disks.MNT / "boot",
    )
    return filesystem


def _uuid(partition: str) -> str:
    return output("blkid", "--match-tag", "UUID", "--output", "value",
                  partition).strip()  # fmt: skip


def country(timezone: str, table: str) -> str | None:
    """The country of a time zone, from tzdata's zone.tab."""
    for line in table.splitlines():
        fields = line.split("	")
        if len(fields) > 2 and fields[2] == timezone:
            return fields[0]
    return None


def _kbd_model_map() -> Path:
    """systemd's table of console keymaps and their X layouts, beside the
    localectl that reads it."""
    localectl = shutil.which("localectl")
    if localectl is None:
        raise SystemExit("localectl is missing: this is not the NixOS ISO.")
    share = Path(localectl).resolve().parent.parent / "share"
    return share / "systemd/kbd-model-map"


def keyboard(keymap: str, table: str) -> dict[str, str]:
    """The X layout for a console keymap, from systemd's kbd-model-map, as
    localectl set-keymap finds it; the desktop and login screen type in it."""
    for line in table.splitlines():
        fields = line.split()
        if fields[:1] == [keymap]:
            values = zip(XKB, fields[1:5], strict=False)
            return {name: value for name, value in values if value != "-"}
    return {}


def gpus(root: Path = Path("/")) -> list[str]:
    """The driver for each GPU: nvidia for NVIDIA's from Turing on, which
    nvidia-open supports, Mesa's (intel, amd, nouveau) for the rest."""
    found = set()
    for device in (root / "sys/bus/pci/devices").iterdir():
        if not (device / "class").read_text().startswith("0x03"):
            continue
        vendor = (device / "vendor").read_text().strip()
        model = int((device / "device").read_text(), 16)
        if vendor == "0x10de" and model >= disks.NVIDIA_TURING:
            found.add("nvidia")
        elif vendor in GRAPHICS:
            found.add(GRAPHICS[vendor])
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


def _create_keys() -> None:
    """Secure Boot keys of the new system's own, made before nixos-install,
    whose lanzaboote signs systemd-boot and the kernel images with them."""
    keys = disks.MNT / SBCTL
    keys.mkdir(mode=0o700, parents=True, exist_ok=True)
    run(
        *NIX, "shell", "nixpkgs#sbctl", "--command", "sbctl", "create-keys",
        "--database-path", keys / "GUID", "--export", keys / "keys",
    )  # fmt: skip


def _enroll_keys(firmware: str) -> None:
    """Enrol the keys, Microsoft's beside them (a graphics card's firmware
    is signed by Microsoft), if the firmware lets them be: in Setup Mode."""
    if firmware != "setup":
        return
    enroll: list[str | Path] = ["nixos-enter", "--root", disks.MNT, "--"]
    if not succeeds(*enroll, "sbctl", "enroll-keys", "--microsoft"):
        warn("Could not enrol the Secure Boot keys: phase 3 says what is left")


def _enter(*command: str, data: str | None = None) -> None:
    run("nixos-enter", "--root", disks.MNT, "--", *command, data=data)
