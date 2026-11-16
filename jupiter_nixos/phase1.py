"""Phase 1: install NixOS from the installation ISO.

The disk is laid out as the Arch installer's phase 1 lays it out: GPT with
a 1 GiB EFI system partition at /boot, and Btrfs subvolumes for everything
else (@nix where Arch has pacman's cache), on LUKS2 unless you decline it: a
passphrase opens it at boot, typed in the console keymap you chose. Other
disks can be erased and encrypted as data disks, mounted where you say:
each opens with a key file on the encrypted system (/etc/cryptsetup-keys.d),
the passphrase being its fallback, and a missing one does not stop the boot.
A disk you do not choose is never written to or opened.

What the Arch installer then does with pacstrap and arch-chroot, the
flake declares (nixos/): this phase writes what it asked and found to
hosts/<hostname>/settings.json, nixos-generate-config's hardware
configuration beside it, both in the copy of this repo it leaves in your
home, and runs nixos-install from that copy. Passwords are set afterwards
with chpasswd, never in the configuration, which lands in the
world-readable store. Encrypted, Secure Boot keys of the system's own are
made first, for lanzaboote to sign with, and enrolled where the firmware
lets them be. The Wi-Fi networks the ISO joined (NetworkManager's) are
joined by the new system too.

The keymap is asked first and loaded at once, so the passphrase and the
passwords are typed in the layout they will be asked in at boot. A rerun
after a failure closes what the failed attempt left open, and offers again
the data disks it had begun to erase (as /run, which lasts until the ISO is
shut down, remembers).
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
from .common import (
    INSTALLER_DIR,
    OS_RELEASE,
    live,
    output,
    run,
    succeeds,
    warn,
    write_settings,
)

MNT = Path("/mnt")
# The disks this live session erased, so a rerun after a failure can erase
# them again: /run is the ISO's, gone once it shuts down.
ERASED = Path("/run/jupiter-erased")
# NetworkManager's saved networks, on the ISO and on the system alike.
NM_CONNECTIONS = Path("etc/NetworkManager/system-connections")
ISO_CONNECTIONS = Path("/") / NM_CONNECTIONS
EFI = Path("/sys/firmware/efi")
# tzdata's table of zones and their countries, as NixOS links it.
ZONE_TAB = Path("/etc/zoneinfo/zone.tab")
ROOT_TYPE = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"  # Linux x86-64 root (/)
DATA_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"  # Linux filesystem data
ROOT_VOLUME = "root"  # /dev/mapper/root, the encrypted system
KEYS = Path("etc/cryptsetup-keys.d")  # a data disk's key file, root's only
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
NVIDIA_TURING = 0x1E00  # nvidia-open supports this device ID and newer
XKB = ("layout", "model", "variant", "options")
LOCALE = re.compile(r"[a-z]{2,3}_[A-Z]{2}(@[a-z]+)?\.UTF-8")
MIN_DISK_GIB = 16  # smaller ones, like floppies, cannot take the system
MIN_DATA_GIB = 1
# Where a data disk may be mounted: a new folder, not one the system owns.
MOUNT_POINT = re.compile(r"(/[a-z0-9][a-z0-9._-]*)+")
SYSTEM_FOLDERS = {
    "bin", "boot", "dev", "efi", "etc", "home", "lib", "lib64", "nix",
    "opt", "proc", "root", "run", "sbin", "srv", "sys", "tmp", "usr", "var",
}  # fmt: skip
HOSTNAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
# The account greetd's module makes for the login screen, which keeps a user
# of that name instead: the login screen would run as them.
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
    """Install NixOS on a disk of your choice and make it bootable."""
    if not live():
        raise SystemExit("Phase 1 runs from the NixOS installation ISO.")
    if not EFI.is_dir():
        raise SystemExit("Boot the ISO in UEFI mode to install.")
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
    hostname = _ask("Hostname", "nixos", HOSTNAME.fullmatch)
    user = _ask("Username", "", _is_new_user)
    passwords = {user: _new_password(user), "root": _new_password("root")}
    zones = _listed("timedatectl", "list-timezones")
    timezone = _ask("Time zone", "UTC", zones)
    locale = _ask("Locale", "en_US.UTF-8", LOCALE.fullmatch)
    if not _yes(f"Erase everything on {disk}? [y/N] ", default=False):
        raise SystemExit("Nothing was changed.")

    esp, root = _partition(disk)
    luks = _encrypt(root, ROOT_VOLUME, passphrase) if encrypt else None
    if luks:
        root = f"/dev/mapper/{ROOT_VOLUME}"
    filesystem = _mount(esp, root)
    volumes = []
    for volume in data:
        data_luks, data_filesystem = _make_data_disk(volume, passphrase)
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
        "nixos-generate-config", "--root", MNT, "--no-filesystems",
        "--show-hardware-config",
    )  # fmt: skip
    (folder / "hardware-configuration.nix").write_text(hardware)
    # A flake in a git repo sees tracked files alone.
    run("git", "-C", copy, "add", "--", f"hosts/{hostname}")
    _carry_wifi()
    if encrypt:
        _create_keys()
    run(
        "nixos-install", "--root", MNT, "--no-root-passwd",
        "--no-channel-copy", "--flake", f"{copy}#{hostname}",
    )  # fmt: skip
    logins = [f"{name}:{password}" for name, password in passwords.items()]
    _enter("chpasswd", data="\n".join(logins) + "\n")
    _enter("chown", "--recursive", f"{user}:", f"/home/{user}")
    for volume in data:
        _own(volume, user)
    if encrypt:
        _enroll_keys(firmware)


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
    keys.mkdir(mode=0o700, exist_ok=True)
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
    _enter("chown", f"{user}:", volume.mount)


def _mount(esp: str, root: str) -> str:
    """Format the ESP and the root, make the subvolumes and mount them all
    at /mnt; returns the Btrfs's UUID."""
    filesystem = str(uuid.uuid4())
    run("mkfs.fat", "-F", "32", esp)
    run("mkfs.btrfs", "--force", f"--uuid={filesystem}", root)
    run("mount", root, MNT)
    run("btrfs", "subvolume", "create", *(MNT / name for name in SUBVOLUMES))
    run("umount", MNT)
    for name, path in SUBVOLUMES.items():
        options = f"compress=zstd,subvol={name}"
        run("mount", "--mkdir", "-o", options, root, MNT / path)
    run("mount", "--mkdir", "-o", "fmask=0077,dmask=0077", esp, MNT / "boot")
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
        if vendor == "0x10de" and model >= NVIDIA_TURING:
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
    folder = MNT / NM_CONNECTIONS
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
    copy = MNT / "home" / user / INSTALLER_DIR.name
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(INSTALLER_DIR, copy, ignore=ignore, symlinks=True)
    return copy


def _create_keys() -> None:
    """Secure Boot keys of the new system's own, made before nixos-install,
    whose lanzaboote signs systemd-boot and the kernel images with them."""
    keys = MNT / SBCTL
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
    enroll: list[str | Path] = ["nixos-enter", "--root", MNT, "--"]
    if not succeeds(*enroll, "sbctl", "enroll-keys", "--microsoft"):
        warn("Could not enrol the Secure Boot keys: phase 3 says what is left")


def _enter(*command: str, data: str | None = None) -> None:
    run("nixos-enter", "--root", MNT, "--", *command, data=data)
