"""Phase 1: install the base system from the live ISO.

The steps are the Arch Linux Installation guide's, with archinstall's
defaults: GPT with a 1 GiB EFI system partition at /boot, Btrfs subvolumes
for everything else, swap on zram and systemd-boot.

The system's Btrfs is on LUKS2 unless you decline it: a passphrase opens it
at boot, typed in the console keymap you chose. Other disks can be erased
and encrypted as data disks, mounted where you say: each opens with a key
file on the encrypted system (/etc/cryptsetup-keys.d), the passphrase being
its fallback, and a missing one does not stop the boot. A disk you do not
choose is never written to or opened.

The keymap is asked first and loaded at once, so the passphrase and the
passwords are typed in the layout they will be asked in at boot. A rerun
after a failure closes what the failed attempt left open, and offers again
the data disks it had begun to erase (as /run, which lasts until the live
ISO is shut down, remembers). The Wi-Fi networks the live ISO joined (with
iwctl) are joined by the new system too, through NetworkManager.
"""

import getpass
import json
import os
import pwd
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import secureboot
from .common import INSTALLER_DIR, LIVE, output, run, succeeds, warn

MNT = Path("/mnt")
# The disks this live session erased, so a rerun after a failure can erase
# them again: /run is the ISO's, gone once it shuts down.
ERASED = Path("/run/jupiter-erased")
# iwd's saved networks on the live ISO, and NetworkManager's on the system.
IWD = Path("/var/lib/iwd")
NM_CONNECTIONS = Path("etc/NetworkManager/system-connections")
# iwd's file name for a network whose name is only these (others: =hex).
IWD_PLAIN_NAME = re.compile(r"[A-Za-z0-9 _-]+")
EFI = Path("/sys/firmware/efi")
LOCALE_GEN = Path("/etc/locale.gen")  # the live ISO's, listing every locale
ROOT_TYPE = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"  # Linux x86-64 root (/)
DATA_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"  # Linux filesystem data
ROOT_VOLUME = "root"  # /dev/mapper/root, the encrypted system
KEYS = Path("etc/cryptsetup-keys.d")  # a data disk's key file, root's only
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
# Encrypted, sbctl for the Secure Boot keys and signatures, and the TPM's
# library, which systemd-cryptsetup opens to unlock with it.
ENCRYPTED_BASE = ["sbctl", "tpm2-tss"]
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
# The initramfs only has to find the root file system. Without kms the
# graphics driver loads beside the rest of the system instead of before it,
# and Btrfs needs no fsck. Unencrypted, nothing is typed there, so the
# console's keymap and font can wait for systemd-vconsole-setup too.
HOOKS = "base udev autodetect microcode modconf keyboard block filesystems"
# Encrypted, systemd's initramfs opens the root (sd-encrypt, from
# /etc/crypttab's x-initrd.attach lines) and asks for the passphrase in the
# console keymap (sd-vconsole). keyboard comes before autodetect, so every
# keyboard driver is in, not only those of the keyboard plugged in now: the
# passphrase may be typed on another. No busybox (base): no shell there, and
# systemd's hook locks root in the initramfs (root:* in its /etc/shadow), so
# its emergency shell refuses: a volume that will not open stops the boot.
ENCRYPTED_HOOKS = (
    "systemd keyboard autodetect microcode modconf sd-vconsole block "
    "sd-encrypt filesystems"
)
MIN_DISK_GIB = 16  # smaller ones, like floppies, cannot take the system
MIN_DATA_GIB = 1
# Where a data disk may be mounted: a new folder, not one the system owns.
MOUNT_POINT = re.compile(r"(/[a-z0-9][a-z0-9._-]*)+")
SYSTEM_FOLDERS = {
    "bin", "boot", "dev", "efi", "etc", "home", "lib", "lib64", "nix",
    "opt", "proc", "root", "run", "sbin", "sys", "tmp", "usr", "var",
}  # fmt: skip
HOSTNAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
# The account greetd's package makes for the login screen in phase 2, which
# keeps a user of that name instead: the login screen would run as them.
RESERVED = {"greeter"}


@dataclass
class DataDisk:
    """A disk to erase and encrypt for data, and where it is mounted."""

    disk: str
    mount: str

    @property
    def name(self) -> str:
        """Its volume's name in /dev/mapper and its key file's."""
        return self.mount.strip("/").replace("/", "-")


def main() -> None:
    """Install Arch Linux on a disk of your choice and make it bootable."""
    if not LIVE:
        raise SystemExit("Phase 1 runs from the Arch Linux live ISO.")
    if not EFI.is_dir():
        raise SystemExit("Boot the live ISO in UEFI mode to install.")
    if MNT.is_mount():
        run("umount", "--recursive", MNT)

    keymaps = _listed("localectl", "list-keymaps")
    keymap = _ask("Keymap", "us", keymaps)
    # The console's own, for the passwords below: as typed at boot. Not a
    # console (over SSH, a serial line), characters arrive as they are.
    subprocess.run(["loadkeys", keymap], check=False, capture_output=True)
    firmware = secureboot.state(EFI / "efivars")
    if firmware == "none":
        print(secureboot.NO_SECURE_BOOT_HELP)
    elif firmware != "setup":
        print(secureboot.SETUP_MODE_HELP)
    devices = _close_leftovers(_devices())
    disk = _choose_disk(devices)
    encrypt = _yes(f"Encrypt {disk}? [Y/n] ", default=True)
    passphrase = _new_password("the disk", "Passphrase") if encrypt else ""
    data = _choose_data_disks(devices, disk) if encrypt else []
    hostname = _ask("Hostname", "archlinux", HOSTNAME.fullmatch)
    user = _ask("Username", "", _is_new_user)
    passwords = {user: _new_password(user), "root": _new_password("root")}
    zones = _listed("timedatectl", "list-timezones")
    timezone = _ask("Time zone", "UTC", zones)
    locale = _ask("Locale", "en_US.UTF-8", _is_locale)
    if not _yes(f"Erase everything on {disk}? [y/N] ", default=False):
        raise SystemExit("Nothing was changed.")

    esp, root = _partition(disk)
    crypttab = ""
    if encrypt:
        luks = _encrypt(root, ROOT_VOLUME, passphrase)
        root = f"/dev/mapper/{ROOT_VOLUME}"
        # Its volume key measured into PCR 15 when it opens, which the TPM
        # binding (phase 4) relies on.
        options = "discard,x-initrd.attach,tpm2-measure-pcr=yes"
        crypttab = f"{ROOT_VOLUME} UUID={luks} none {options}\n"
    _mount(esp, root)
    _write_settings(hostname, timezone, locale, keymap, encrypt)
    if encrypt:
        _write_kernel_image_settings()
    mounts = ""
    for volume in data:
        luks, filesystem = _make_data_disk(volume, passphrase)
        key = Path("/", KEYS, f"{volume.name}.key")
        # A missing data disk is waited for 10 s, not systemd's 90, and never
        # holds up the boot (nofail): data disks are internal, there or not.
        wait = "nofail,x-systemd.device-timeout=10s"
        crypttab += f"{volume.name} UUID={luks} {key} discard,{wait}\n"
        options = f"compress=zstd,{wait}"
        mounts += f"UUID={filesystem} {volume.mount} btrfs {options} 0 0\n"
    graphics = drivers()
    if "nvidia-open" in graphics and "mesa" not in graphics:  # NVIDIA only
        env = MNT / "etc/xdg/uwsm/env-hyprland"  # uwsm reads it for Hyprland
        env.parent.mkdir(parents=True)
        env.write_text(NVIDIA_ENV)
    extra = ENCRYPTED_BASE if encrypt else []
    run("pacstrap", "-K", MNT, *BASE, *extra, *graphics)
    with (MNT / "etc/fstab").open("a") as fstab:
        fstab.write(output("genfstab", "-U", MNT) + mounts)
    if encrypt:
        # After pacstrap: systemd's package ships an empty one.
        (MNT / "etc/crypttab").write_text(crypttab)
    _configure(user, passwords, locale)
    _carry_wifi()
    for volume in data:
        _own(volume, user)
    if encrypt:
        _sign_boot(firmware)
    _install_boot_loader(entry=not encrypt)
    if encrypt:
        # The image pacstrap built had no crypttab to open the root by, and
        # no keys to be signed with.
        _chroot("mkinitcpio", "--allpresets")
        _chroot("systemctl", "enable", "systemd-boot-update.service")
    _copy_installer(user)


def _ask(question: str, default: str, valid: Callable[[str], object]) -> str:
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    while True:
        answer = input(prompt).strip() or default
        if valid(answer):
            return answer
        print(f"{answer!r} is not a valid {question.lower()}.")


def _yes(question: str, default: bool) -> bool:
    answer = input(question).strip().lower()
    return answer.startswith("y") if answer else default


def _new_password(user: str, kind: str = "Password") -> str:
    while True:
        password = getpass.getpass(f"{kind} for {user}: ")
        if password and password == getpass.getpass("Repeat it: "):
            return password
        print(f"The {kind.lower()}s were empty or did not match.")


def _is_new_user(name: str) -> bool:
    taken = {entry.pw_name for entry in pwd.getpwall()} | RESERVED
    return bool(USERNAME.fullmatch(name)) and name not in taken


def _is_locale(name: str) -> bool:
    return f"\n#{name} UTF-8" in LOCALE_GEN.read_text()


def _listed(*command: str) -> Callable[[str], bool]:
    return set(output(*command).split()).__contains__


def _devices() -> list[dict[str, Any]]:
    columns = "NAME,SIZE,MODEL,TYPE,MOUNTPOINTS,FSTYPE,PTTYPE"
    lsblk = ["lsblk", "--json", "--bytes", "--paths", "-o", columns]
    devices: list[dict[str, Any]] = json.loads(output(*lsblk))["blockdevices"]
    return devices


def _choose_disk(devices: list[dict[str, Any]]) -> str:
    disks = targets(devices)
    if not disks:
        raise SystemExit(f"No unused disk has {MIN_DISK_GIB} GiB or more.")
    for disk in disks:
        held = ", ".join(_holds(disk)) or "empty"
        print(f"  {_describe(disk)}  ({held})")
    names = {disk["name"] for disk in disks}
    # More than one: no default, as Enter could pick another system's disk.
    default = disks[0]["name"] if len(disks) == 1 else ""
    return _ask("Disk", default, names.__contains__)


def _describe(disk: dict[str, Any]) -> str:
    size = disk["size"] // 2**30
    return f"{disk['name']}  {size} GiB  {disk['model'] or ''}".rstrip()


def _choose_data_disks(
    devices: list[dict[str, Any]], system: str
) -> list[DataDisk]:
    """Ask, disk by disk, which others to erase and encrypt for data.

    Only an empty disk is offered, or one an earlier attempt from this
    live ISO erased: one with a file system or a partition table (Windows',
    say) or anything mounted is listed as left alone.
    """
    erased = _erased()
    others = [
        device
        for device in devices
        if device["type"] == "disk"
        and device["name"] != system
        and device["size"] >= MIN_DATA_GIB * 2**30
    ]
    chosen: list[DataDisk] = []
    for disk in others:
        if _in_use(disk) or (_holds(disk) and disk["name"] not in erased):
            what = "in use" if _in_use(disk) else ", ".join(_holds(disk))
            print(f"  {_describe(disk)}: left alone ({what})")
            continue
        question = f"Erase and encrypt {_describe(disk)} for data? [y/N] "
        if not _yes(question, default=False):
            continue
        taken = {volume.mount for volume in chosen}
        number = len(chosen) + 1
        default = "/data" if number == 1 else f"/data{number}"
        mount = _ask("Mount it at", default, _mount_point(taken))
        if _yes(f"Erase everything on {disk['name']}? [y/N] ", default=False):
            chosen.append(DataDisk(disk["name"], mount))
    return chosen


def _erased() -> set[str]:
    """The disks an earlier attempt from this live ISO erased for data."""
    return set(ERASED.read_text().split()) if ERASED.exists() else set()


def _close_leftovers(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close the encrypted volumes an earlier attempt left open (the live
    ISO opens none itself), so their disks can be erased again; lsblk's list
    again if any was."""
    opened = [
        device["name"]
        for disk in devices
        for device in _descendants(disk)
        if device["type"] == "crypt" and not _in_use(device)
    ]
    for name in opened:
        run("cryptsetup", "close", name)
    return _devices() if opened else devices


def _descendants(device: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for child in device.get("children", []):
        found += [child, *_descendants(child)]
    return found


def _holds(device: dict[str, Any]) -> list[str]:
    """The partition table and file systems on a device, if any."""
    found = [kind for key in ("pttype", "fstype") if (kind := device.get(key))]
    for child in device.get("children", []):
        found += [kind for kind in _holds(child) if kind not in found]
    return found


def _mount_point(taken: set[str]) -> Callable[[str], bool]:
    """Whether a path can take a data disk: a new folder, not the system's
    and not another data disk's."""

    def valid(path: str) -> bool:
        return (
            bool(MOUNT_POINT.fullmatch(path))
            and path.split("/")[1] not in SYSTEM_FOLDERS
            and path not in taken
            and DataDisk("", path).name != ROOT_VOLUME
        )

    return valid


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


def _encrypt(partition: str, name: str, passphrase: str) -> str:
    """LUKS2 on a partition, opened as /dev/mapper/name; returns its UUID.

    The passphrase goes on stdin, as typed: no newline after it, as none
    follows it when it is typed at boot.
    """
    luks = str(uuid.uuid4())
    key = ["--key-file=-"]
    run(
        "cryptsetup",
        "luksFormat",
        "--type=luks2",
        "--batch-mode",
        f"--uuid={luks}",
        *key,
        partition,
        data=passphrase,
    )
    run("cryptsetup", "open", *key, partition, name, data=passphrase)
    return luks


def _make_data_disk(volume: DataDisk, passphrase: str) -> tuple[str, str]:
    """Erase a data disk: one partition, LUKS2 opened by a key file of its
    own or the passphrase, and Btrfs. Returns the LUKS and Btrfs UUIDs."""
    with ERASED.open("a") as erased:
        erased.write(f"{volume.disk}\n")
    wipe = ["--wipe", "always", "--wipe-partitions", "always"]
    run("sfdisk", *wipe, volume.disk, data=f"label: gpt\ntype={DATA_TYPE}\n")
    run("udevadm", "settle")
    table = json.loads(output("sfdisk", "--json", volume.disk))
    partition = table["partitiontable"]["partitions"][0]["node"]
    luks = _encrypt(partition, volume.name, passphrase)
    keys = MNT / KEYS
    # parents: NixOS's phase 1 erases data disks before nixos-install makes
    # /mnt/etc; Arch's pacstrap has made it by then.
    keys.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = keys / f"{volume.name}.key"
    # Created 0400, so no one else could ever read it, then filled.
    with os.fdopen(
        os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), "wb"
    ) as file:
        file.write(os.urandom(64))
    # Random already: a key derivation that costs no time at boot. Slot 1,
    # tried first (prefer): otherwise the key file is first tried against
    # the passphrase's slot, whose Argon2id takes seconds and a GiB.
    run(
        "cryptsetup",
        "luksAddKey",
        "--batch-mode",
        "--pbkdf=pbkdf2",
        "--pbkdf-force-iterations=1000",
        "--new-key-slot=1",
        "--key-file=-",
        partition,
        key,
        data=passphrase,
    )
    run("cryptsetup", "config", "--key-slot=1", "--priority=prefer", partition)
    filesystem = str(uuid.uuid4())
    run(
        "mkfs.btrfs",
        "--force",
        f"--uuid={filesystem}",
        f"/dev/mapper/{volume.name}",
    )
    return luks, filesystem


def _own(volume: DataDisk, user: str) -> None:
    """Mount a data disk where it goes and give its top folder to the user."""
    run(
        "mount",
        "--mkdir",
        "-o",
        "compress=zstd",
        f"/dev/mapper/{volume.name}",
        MNT / volume.mount.lstrip("/"),
    )
    _chroot("chown", f"{user}:", volume.mount)


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
    hostname: str, timezone: str, locale: str, keymap: str, encrypt: bool
) -> None:
    """Write the settings no package owns.

    They go in before pacstrap, so the initramfs it builds has these hooks.
    """
    etc = MNT / "etc"
    (etc / "systemd").mkdir(parents=True)
    (etc / "mkinitcpio.conf.d").mkdir()
    hooks = ENCRYPTED_HOOKS if encrypt else HOOKS
    (etc / "mkinitcpio.conf.d/jupiter.conf").write_text(f"HOOKS=({hooks})\n")
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
            values = zip(XKB, fields[1:5], strict=False)
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


def _carry_wifi() -> None:
    """A NetworkManager connection for each WPA network the live ISO saved
    with iwctl, so the new system joins it after the reboot. Only a network
    with a plain name and a passphrase: others are joined again with nmtui."""
    if not IWD.is_dir():
        return
    folder = MNT / NM_CONNECTIONS
    for saved in sorted(IWD.glob("*.psk")):
        name = saved.stem
        found = re.search(r"^Passphrase=(.+)$", saved.read_text(), re.M)
        if not IWD_PLAIN_NAME.fullmatch(name) or not found:
            continue
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        # A key file's string: a backslash escaped, a leading space kept.
        psk = found.group(1).replace("\\", "\\\\")
        psk = "\\s" + psk[1:] if psk.startswith(" ") else psk
        text = (
            f"[connection]\nid={name}\ntype=wifi\n\n"
            f"[wifi]\nmode=infrastructure\nssid={name}\n\n"
            f"[wifi-security]\nkey-mgmt=wpa-psk\npsk={psk}\n\n"
            "[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n"
        )
        path = folder / f"{name}.nmconnection"
        # Created 0600, root's, as NetworkManager insists, then filled.
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as file:
            file.write(text)


def _command_line(encrypt: bool) -> str:
    """The kernel's command line. Encrypted, the root is named by its opened
    volume, which only systemd-cryptsetup makes, from crypttab's line: its
    key measured into PCR 15, and the one fixed there (tpm.py). By its file
    system's UUID, a disk without encryption carrying that UUID would be
    mounted in the root's place with no volume opened, PCR 15 still zero,
    and the TPM would give that system the key."""
    if encrypt:
        root = f"/dev/mapper/{ROOT_VOLUME}"
    else:
        uuid = output("findmnt", "--noheadings", "-o", "UUID", MNT).strip()
        root = f"UUID={uuid}"
    return (
        f"root={root} rootflags=subvol=@ rw zswap.enabled=0 quiet loglevel=3"
    )


def _write_kernel_image_settings() -> None:
    """A unified kernel image, with its command line in it, is all mkinitcpio
    builds; before pacstrap, which builds the first (or mkinitcpio would
    take the live ISO's command line)."""
    (MNT / "etc/kernel").mkdir()
    (MNT / "etc/kernel/cmdline").write_text(f"{_command_line(True)}\n")
    (MNT / "etc/mkinitcpio.d").mkdir()
    (MNT / "etc/mkinitcpio.d/linux.preset").write_text(secureboot.PRESET)


def _sign_boot(firmware: str) -> None:
    """Secure Boot keys of the new system's own, enrolled if the firmware
    lets them be, and systemd-boot signed: bootctl installs the signed copy,
    and sbctl signs it again whenever systemd updates it."""
    _chroot("sbctl", "create-keys")
    enroll: list[str | Path] = ["arch-chroot", "-S", MNT]
    enroll += ["sbctl", "enroll-keys", "--microsoft"]
    if firmware == "setup" and not succeeds(*enroll):
        warn("Could not enrol the Secure Boot keys: phase 4 says what is left")
    boot = str(secureboot.BOOT_EFI)
    signed = str(secureboot.SIGNED_BOOT_EFI)
    _chroot("sbctl", "sign", "--save", "--output", signed, boot)


def _install_boot_loader(entry: bool = True) -> None:
    """systemd-boot, with a loader entry for the kernel and its initramfs
    unencrypted; encrypted, it finds the unified kernel image by itself."""
    _chroot("bootctl", "install")
    if entry:
        path = MNT / "boot/loader/entries/arch.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "title   Arch Linux\n"
            "linux   /vmlinuz-linux\n"
            "initrd  /initramfs-linux.img\n"
            f"options {_command_line(False)}\n"
        )
    # No menu to wait at: holding Space at power-on still brings it up.
    loader = MNT / "boot/loader/loader.conf"
    loader.parent.mkdir(parents=True, exist_ok=True)
    text = loader.read_text() if loader.exists() else ""
    if not re.search(r"^timeout\b", text, re.MULTILINE):
        loader.write_text(text + "timeout 0\n")


def _copy_installer(user: str) -> None:
    """Leave this installer in the new home, to run phases 3 and 4 from."""
    copy = Path("home", user, INSTALLER_DIR.name)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(INSTALLER_DIR, MNT / copy, ignore=ignore)
    _chroot("chown", "--recursive", f"{user}:", f"/{copy}")


def _chroot(*command: str, data: str | None = None) -> None:
    run("arch-chroot", "-S", MNT, *command, data=data)
