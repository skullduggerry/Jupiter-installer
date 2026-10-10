"""Phase 1: install the base system from the live ISO.

The steps are the Arch Linux Installation guide's, with archinstall's
defaults: GPT with a 1 GiB EFI system partition at /boot, Btrfs subvolumes
for everything else, swap on zram and systemd-boot.
"""

import getpass
import json
import pwd
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .common import INSTALLER_DIR, LIVE, output, run

MNT = Path("/mnt")
ROOT_TYPE = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"  # Linux x86-64 root (/)
SUBVOLUMES = {
    "@": "",
    "@home": "home",
    "@log": "var/log",
    "@pkg": "var/cache/pacman/pkg",
}
BASE = [
    "base",
    "linux",
    "mkinitcpio",
    "linux-firmware",
    "sof-firmware",
    "btrfs-progs",
    "zram-generator",
    "networkmanager",
    "sudo",
    "git",
    "python",
]
MICROCODE = {"GenuineIntel": "intel-ucode", "AuthenticAMD": "amd-ucode"}
GRAPHICS = {
    "0x8086": ["mesa", "vulkan-intel", "intel-media-driver"],
    "0x1002": ["mesa", "vulkan-radeon"],
    "0x10de": ["mesa", "vulkan-nouveau"],
}
NVIDIA = ["nvidia-open", "libva-nvidia-driver"]
NVIDIA_TURING = 0x1E00  # nvidia-open supports this device ID and newer
NVIDIA_ENV = """\
# From the Hyprland wiki's Nvidia page, for a machine whose only GPU is one.
export LIBVA_DRIVER_NAME=nvidia
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export NVD_BACKEND=direct
"""
KBD_MODEL_MAP = Path("/usr/share/systemd/kbd-model-map")
XKB = ("XKBLAYOUT", "XKBMODEL", "XKBVARIANT", "XKBOPTIONS")
MIN_DISK_GIB = 16  # smaller ones, like floppies, cannot take the system
HOSTNAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


def main() -> None:
    """Install Arch Linux on a disk of your choice and make it bootable."""
    if not LIVE:
        raise SystemExit("Phase 1 runs from the Arch Linux live ISO.")
    if not Path("/sys/firmware/efi").is_dir():
        raise SystemExit("Boot the live ISO in UEFI mode to install.")
    if MNT.is_mount():
        run("umount", "--recursive", MNT)

    disk = _choose_disk()
    hostname = _ask("Hostname", "archlinux", HOSTNAME.fullmatch)
    user = _ask("Username", "", _is_new_user)
    passwords = {user: _new_password(user), "root": _new_password("root")}
    zones = _listed("timedatectl", "list-timezones")
    timezone = _ask("Time zone", "UTC", zones)
    locale = _ask("Locale", "en_US.UTF-8", _is_locale)
    keymaps = _listed("localectl", "list-keymaps")
    keymap = _ask("Keymap", "us", keymaps)
    if input(f"Erase everything on {disk}? [y/N] ").strip().lower() != "y":
        raise SystemExit("Nothing was changed.")

    esp, root = _partition(disk)
    _mount(esp, root)
    _write_settings(hostname, timezone, locale, keymap)
    graphics = drivers()
    if "nvidia-open" in graphics and "mesa" not in graphics:  # NVIDIA only
        env = MNT / "etc/xdg/uwsm/env-hyprland"  # uwsm reads it for Hyprland
        env.parent.mkdir(parents=True)
        env.write_text(NVIDIA_ENV)
    run("pacstrap", "-K", MNT, *BASE, *graphics)
    with (MNT / "etc/fstab").open("a") as fstab:
        fstab.write(output("genfstab", "-U", MNT))
    _configure(user, passwords, locale)
    _install_boot_loader()
    _copy_installer(user)


def _ask(question: str, default: str, valid: Callable[[str], object]) -> str:
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    while True:
        answer = input(prompt).strip() or default
        if valid(answer):
            return answer
        print(f"{answer!r} is not a valid {question.lower()}.")


def _new_password(user: str) -> str:
    while True:
        password = getpass.getpass(f"Password for {user}: ")
        if password and password == getpass.getpass("Repeat it: "):
            return password
        print("The passwords were empty or did not match.")


def _is_new_user(name: str) -> bool:
    taken = {entry.pw_name for entry in pwd.getpwall()}
    return bool(USERNAME.fullmatch(name)) and name not in taken


def _is_locale(name: str) -> bool:
    return f"\n#{name} UTF-8" in Path("/etc/locale.gen").read_text()


def _listed(*command: str) -> Callable[[str], bool]:
    return set(output(*command).split()).__contains__


def _choose_disk() -> str:
    columns = "NAME,SIZE,MODEL,TYPE,MOUNTPOINTS"
    lsblk = ["lsblk", "--json", "--bytes", "--paths", "-o", columns]
    disks = targets(json.loads(output(*lsblk))["blockdevices"])
    if not disks:
        raise SystemExit(f"No unused disk has {MIN_DISK_GIB} GiB or more.")
    for disk in disks:
        size = disk["size"] // 2**30
        print(f"  {disk['name']}  {size} GiB  {disk['model'] or ''}")
    names = {disk["name"] for disk in disks}
    return _ask("Disk", disks[0]["name"], names.__contains__)


def targets(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the unused disks the system fits on from lsblk's --bytes list."""
    return [
        device
        for device in devices
        if device["type"] == "disk"
        and device["size"] >= MIN_DISK_GIB * 2**30
        and not _in_use(device)
    ]


def _in_use(device: dict[str, Any]) -> bool:
    children = device.get("children", [])
    return any(device["mountpoints"]) or any(map(_in_use, children))


def _partition(disk: str) -> tuple[str, str]:
    layout = f"label: gpt\nsize=1GiB, type=uefi\ntype={ROOT_TYPE}\n"
    wipe = ["--wipe", "always", "--wipe-partitions", "always"]
    run("sfdisk", *wipe, disk, data=layout)
    run("udevadm", "settle")
    table = json.loads(output("sfdisk", "--json", disk))["partitiontable"]
    esp, root = (partition["node"] for partition in table["partitions"])
    return esp, root


def _mount(esp: str, root: str) -> None:
    run("mkfs.fat", "-F", "32", esp)
    run("mkfs.btrfs", "--force", root)
    run("mount", root, MNT)
    run("btrfs", "subvolume", "create", *(MNT / name for name in SUBVOLUMES))
    run("umount", MNT)
    for name, path in SUBVOLUMES.items():
        options = f"compress=zstd,subvol={name}"
        run("mount", "--mkdir", "-o", options, root, MNT / path)
    run("mount", "--mkdir", "-o", "fmask=0077,dmask=0077", esp, MNT / "boot")


def _write_settings(
    hostname: str, timezone: str, locale: str, keymap: str
) -> None:
    """Write the settings no package owns.

    They go in before pacstrap, so the initramfs it builds has the keymap.
    """
    etc = MNT / "etc"
    (etc / "systemd").mkdir(parents=True)
    (etc / "hostname").write_text(f"{hostname}\n")
    (etc / "locale.conf").write_text(f"LANG={locale}\n")
    xkb = keyboard(keymap, KBD_MODEL_MAP.read_text())
    lines = [f"{key}={value}\n" for key, value in xkb.items()]
    (etc / "vconsole.conf").write_text("".join([f"KEYMAP={keymap}\n", *lines]))
    (etc / "systemd/zram-generator.conf").write_text("[zram0]\n")
    (etc / "localtime").symlink_to(f"/usr/share/zoneinfo/{timezone}")


def keyboard(keymap: str, table: str) -> dict[str, str]:
    """The X layout for a console keymap, from systemd's kbd-model-map.

    localectl set-keymap writes the same beside KEYMAP; the dotfiles'
    desktop and login screen type in it.
    """
    for line in table.splitlines():
        fields = line.split()
        if fields[:1] == [keymap]:
            values = zip(XKB, fields[1:5])
            return {name: value for name, value in values if value != "-"}
    return {}


def drivers(root: Path = Path("/")) -> set[str]:
    """Microcode for the CPU, and the graphics drivers of every GPU."""
    cpu = (root / "proc/cpuinfo").read_text()
    found = {package for vendor, package in MICROCODE.items() if vendor in cpu}
    for device in (root / "sys/bus/pci/devices").iterdir():
        if not (device / "class").read_text().startswith("0x03"):
            continue
        vendor = (device / "vendor").read_text().strip()
        model = int((device / "device").read_text(), 16)
        if vendor == "0x10de" and model >= NVIDIA_TURING:
            found.update(NVIDIA)
        else:
            found.update(GRAPHICS.get(vendor, []))
    return found


def _configure(user: str, passwords: dict[str, str], locale: str) -> None:
    locale_gen = MNT / "etc/locale.gen"
    entry = f"{locale} UTF-8"
    text = locale_gen.read_text().replace(f"\n#{entry}", f"\n{entry}")
    locale_gen.write_text(text)
    _chroot("locale-gen")
    _chroot("hwclock", "--systohc")
    _chroot("useradd", "--create-home", "--groups", "wheel", user)
    logins = [f"{name}:{password}" for name, password in passwords.items()]
    _chroot("chpasswd", data="\n".join(logins) + "\n")
    sudoers = MNT / "etc/sudoers.d/10-wheel"
    sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
    sudoers.chmod(0o440)
    _chroot("systemctl", "enable", "NetworkManager", "systemd-timesyncd")


def _install_boot_loader() -> None:
    _chroot("bootctl", "install")
    uuid = output("findmnt", "--noheadings", "-o", "UUID", MNT).strip()
    entry = MNT / "boot/loader/entries/arch.conf"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "title   Arch Linux\n"
        "linux   /vmlinuz-linux\n"
        "initrd  /initramfs-linux.img\n"
        f"options root=UUID={uuid} rootflags=subvol=@ rw zswap.enabled=0\n"
    )


def _copy_installer(user: str) -> None:
    """Leave this installer in the new home, to run phases 3 and 4 from."""
    copy = Path("home", user, INSTALLER_DIR.name)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(INSTALLER_DIR, MNT / copy, ignore=ignore)
    _chroot("chown", "--recursive", f"{user}:", f"/{copy}")


def _chroot(*command: str, data: str | None = None) -> None:
    run("arch-chroot", "-S", MNT, *command, data=data)
