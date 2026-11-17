"""Phase 1 on Arch: install the base system from the Arch live ISO.

The steps are the Arch Linux Installation guide's, with archinstall's
defaults: Btrfs subvolumes, swap on zram and systemd-boot, with a signed
unified kernel image on an encrypted system. The questions (questions.py)
and the disks (disks.py: the system's disk, LUKS2 unless declined, data
disks) are the same on NixOS; what follows them is Arch's.

The keymap is asked first and loaded at once, so the passphrase and the
passwords are typed in the layout they will be asked in at boot. The Wi-Fi
networks the live ISO joined (with iwctl) are joined by the new system too,
through NetworkManager.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import disks, questions, secureboot
from ..common import (
    INSTALLER_DIR,
    LIVE,
    NVIDIA_TURING,
    output,
    run,
    succeeds,
    warn,
)

# iwd's saved networks on the live ISO, and NetworkManager's on the system.
IWD = Path("/var/lib/iwd")
NM_CONNECTIONS = Path("etc/NetworkManager/system-connections")
# iwd's file name for a network whose name is only these (others: =hex).
IWD_PLAIN_NAME = re.compile(r"[A-Za-z0-9 _-]+")
LOCALE_GEN = Path("/etc/locale.gen")  # the live ISO's, listing every locale
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


def main() -> None:
    """Install Arch Linux on a disk of your choice and make it bootable."""
    if not LIVE:
        raise SystemExit("Phase 1 runs from the Arch Linux live ISO.")
    if not disks.EFI.is_dir():
        raise SystemExit("Boot the live ISO in UEFI mode to install.")
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
    hostname = questions.ask(
        "Hostname", "archlinux", questions.HOSTNAME.fullmatch
    )
    user = questions.ask("Username", "", questions.is_new_user)
    passwords = {
        user: questions.new_password(user),
        "root": questions.new_password("root"),
    }
    zones = questions.listed("timedatectl", "list-timezones")
    timezone = questions.ask("Time zone", "UTC", zones)
    locale = questions.ask("Locale", "en_US.UTF-8", _is_locale)
    if not questions.yes(f"Erase everything on {disk}? [y/N] ", default=False):
        raise SystemExit("Nothing was changed.")

    esp, root = disks.partition(disk)
    crypttab = ""
    if encrypt:
        luks = disks.encrypt(root, disks.ROOT_VOLUME, passphrase)
        root = f"/dev/mapper/{disks.ROOT_VOLUME}"
        # Its volume key measured into PCR 15 when it opens, which the TPM
        # binding (phase 4) relies on.
        options = "discard,x-initrd.attach,tpm2-measure-pcr=yes"
        crypttab = f"{disks.ROOT_VOLUME} UUID={luks} none {options}\n"
    _mount(esp, root)
    _write_settings(hostname, timezone, locale, keymap, encrypt)
    if encrypt:
        _write_kernel_image_settings()
    mounts = ""
    for volume in data:
        luks, filesystem = disks.make_data_disk(volume, passphrase)
        key = Path("/", disks.KEYS, f"{volume.name}.key")
        # A missing data disk is waited for 10 s, not systemd's 90, and never
        # holds up the boot (nofail): data disks are internal, there or not.
        wait = "nofail,x-systemd.device-timeout=10s"
        crypttab += f"{volume.name} UUID={luks} {key} discard,{wait}\n"
        options = f"compress=zstd,{wait}"
        mounts += f"UUID={filesystem} {volume.mount} btrfs {options} 0 0\n"
    graphics = drivers()
    if "nvidia-open" in graphics and "mesa" not in graphics:  # NVIDIA only
        # uwsm reads it for Hyprland.
        env = disks.MNT / "etc/xdg/uwsm/env-hyprland"
        env.parent.mkdir(parents=True)
        env.write_text(NVIDIA_ENV)
    extra = ENCRYPTED_BASE if encrypt else []
    run("pacstrap", "-K", disks.MNT, *BASE, *extra, *graphics)
    with (disks.MNT / "etc/fstab").open("a") as fstab:
        fstab.write(output("genfstab", "-U", disks.MNT) + mounts)
    if encrypt:
        # After pacstrap: systemd's package ships an empty one.
        (disks.MNT / "etc/crypttab").write_text(crypttab)
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


def _is_locale(name: str) -> bool:
    return f"\n#{name} UTF-8" in LOCALE_GEN.read_text()


def _own(volume: disks.DataDisk, user: str) -> None:
    """Mount a data disk where it goes and give its top folder to the user."""
    run(
        "mount",
        "--mkdir",
        "-o",
        "compress=zstd",
        f"/dev/mapper/{volume.name}",
        disks.MNT / volume.mount.lstrip("/"),
    )
    _chroot("chown", f"{user}:", volume.mount)


def _mount(esp: str, root: str) -> None:
    run("mkfs.fat", "-F", "32", esp)
    run("mkfs.btrfs", "--force", root)
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


def _write_settings(
    hostname: str, timezone: str, locale: str, keymap: str, encrypt: bool
) -> None:
    """Write the settings no package owns.

    They go in before pacstrap, so the initramfs it builds has these hooks.
    """
    etc = disks.MNT / "etc"
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
    locale_gen = disks.MNT / "etc/locale.gen"
    entry = f"{locale} UTF-8"
    text = locale_gen.read_text().replace(f"\n#{entry}", f"\n{entry}")
    locale_gen.write_text(text)
    _chroot("locale-gen")
    _chroot("hwclock", "--systohc")
    _chroot("useradd", "--create-home", "--groups", "wheel", user)
    logins = [f"{name}:{password}" for name, password in passwords.items()]
    _chroot("chpasswd", data="\n".join(logins) + "\n")
    sudoers = disks.MNT / "etc/sudoers.d/10-wheel"
    sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
    sudoers.chmod(0o440)
    _chroot("systemctl", "enable", "NetworkManager", "systemd-timesyncd")


def _carry_wifi() -> None:
    """A NetworkManager connection for each WPA network the live ISO saved
    with iwctl, so the new system joins it after the reboot. Only a network
    with a plain name and a passphrase: others are joined again with nmtui."""
    if not IWD.is_dir():
        return
    folder = disks.MNT / NM_CONNECTIONS
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
        root = f"/dev/mapper/{disks.ROOT_VOLUME}"
    else:
        uuid = output(
            "findmnt", "--noheadings", "-o", "UUID", disks.MNT
        ).strip()
        root = f"UUID={uuid}"
    return (
        f"root={root} rootflags=subvol=@ rw zswap.enabled=0 quiet loglevel=3"
    )


def _write_kernel_image_settings() -> None:
    """A unified kernel image, with its command line in it, is all mkinitcpio
    builds; before pacstrap, which builds the first (or mkinitcpio would
    take the live ISO's command line)."""
    (disks.MNT / "etc/kernel").mkdir()
    (disks.MNT / "etc/kernel/cmdline").write_text(f"{_command_line(True)}\n")
    (disks.MNT / "etc/mkinitcpio.d").mkdir()
    (disks.MNT / "etc/mkinitcpio.d/linux.preset").write_text(secureboot.PRESET)


def _sign_boot(firmware: str) -> None:
    """Secure Boot keys of the new system's own, enrolled if the firmware
    lets them be, and systemd-boot signed: bootctl installs the signed copy,
    and sbctl signs it again whenever systemd updates it."""
    _chroot("sbctl", "create-keys")
    enroll: list[str | Path] = ["arch-chroot", "-S", disks.MNT]
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
        path = disks.MNT / "boot/loader/entries/arch.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "title   Arch Linux\n"
            "linux   /vmlinuz-linux\n"
            "initrd  /initramfs-linux.img\n"
            f"options {_command_line(False)}\n"
        )
    # No menu to wait at: holding Space at power-on still brings it up.
    loader = disks.MNT / "boot/loader/loader.conf"
    loader.parent.mkdir(parents=True, exist_ok=True)
    text = loader.read_text() if loader.exists() else ""
    if not re.search(r"^timeout\b", text, re.MULTILINE):
        loader.write_text(text + "timeout 0\n")


def _copy_installer(user: str) -> None:
    """Leave this installer in the new home, to run phases 3 and 4 from."""
    copy = Path("home", user, INSTALLER_DIR.name)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(INSTALLER_DIR, disks.MNT / copy, ignore=ignore)
    _chroot("chown", "--recursive", f"{user}:", f"/{copy}")


def _chroot(*command: str, data: str | None = None) -> None:
    run("arch-chroot", "-S", disks.MNT, *command, data=data)
