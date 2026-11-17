"""The disks both phase 1s lay out from the live ISO: which disk to erase,
GPT with a 1 GiB EFI system partition and the root, LUKS2 on the root
unless declined, and other empty disks erased and encrypted for data when
chosen. A disk not chosen is never written to or opened.

A data disk opens with a key file on the encrypted system
(/etc/cryptsetup-keys.d), the passphrase being its fallback, and a missing
one does not stop the boot. A rerun after a failure closes what the failed
attempt left open, and offers again the data disks it had begun to erase
(as /run, which lasts until the live ISO is shut down, remembers).

What goes on the disks then is each system's own: Arch's subvolumes and
pacstrap (jupiter/arch/phase1.py), NixOS's subvolumes and nixos-install
(jupiter/nixos/phase1.py).
"""

import json
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import output, run
from .questions import ask, yes

MNT = Path("/mnt")
# The disks this live session erased, so a rerun after a failure can erase
# them again: /run is the ISO's, gone once it shuts down.
ERASED = Path("/run/jupiter-erased")
EFI = Path("/sys/firmware/efi")  # the layout boots by UEFI only
ROOT_TYPE = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"  # Linux x86-64 root (/)
DATA_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"  # Linux filesystem data
ROOT_VOLUME = "root"  # /dev/mapper/root, the encrypted system
KEYS = Path("etc/cryptsetup-keys.d")  # a data disk's key file, root's only
MIN_DISK_GIB = 16  # smaller ones, like floppies, cannot take the system
MIN_DATA_GIB = 1
# Where a data disk may be mounted: a new folder, not one the system owns.
MOUNT_POINT = re.compile(r"(/[a-z0-9][a-z0-9._-]*)+")
SYSTEM_FOLDERS = {
    "bin", "boot", "dev", "efi", "etc", "home", "lib", "lib64", "nix",
    "opt", "proc", "root", "run", "sbin", "sys", "tmp", "usr", "var",
}  # fmt: skip


@dataclass
class DataDisk:
    """A disk to erase and encrypt for data, and where it is mounted."""

    disk: str
    mount: str

    @property
    def name(self) -> str:
        """Its volume's name in /dev/mapper and its key file's."""
        return self.mount.strip("/").replace("/", "-")


def devices() -> list[dict[str, Any]]:
    """lsblk's tree of block devices, sizes in bytes."""
    columns = "NAME,SIZE,MODEL,TYPE,MOUNTPOINTS,FSTYPE,PTTYPE"
    lsblk = ["lsblk", "--json", "--bytes", "--paths", "-o", columns]
    found: list[dict[str, Any]] = json.loads(output(*lsblk))["blockdevices"]
    return found


def choose_disk(found: list[dict[str, Any]]) -> str:
    """Ask which disk takes the system, showing what each holds."""
    disks = targets(found)
    if not disks:
        raise SystemExit(f"No unused disk has {MIN_DISK_GIB} GiB or more.")
    for disk in disks:
        held = ", ".join(holds(disk)) or "empty"
        print(f"  {describe(disk)}  ({held})")
    names = {disk["name"] for disk in disks}
    # More than one: no default, as Enter could pick another system's disk.
    default = disks[0]["name"] if len(disks) == 1 else ""
    return ask("Disk", default, names.__contains__)


def describe(disk: dict[str, Any]) -> str:
    """A disk's name, size and model, on one line."""
    size = disk["size"] // 2**30
    return f"{disk['name']}  {size} GiB  {disk['model'] or ''}".rstrip()


def choose_data_disks(
    found: list[dict[str, Any]], system: str
) -> list[DataDisk]:
    """Ask, disk by disk, which others to erase and encrypt for data.

    Only an empty disk is offered, or one an earlier attempt from this
    live ISO erased: one with a file system or a partition table (Windows',
    say) or anything mounted is listed as left alone.
    """
    earlier = erased()
    others = [
        device
        for device in found
        if device["type"] == "disk"
        and device["name"] != system
        and device["size"] >= MIN_DATA_GIB * 2**30
    ]
    chosen: list[DataDisk] = []
    for disk in others:
        if in_use(disk) or (holds(disk) and disk["name"] not in earlier):
            what = "in use" if in_use(disk) else ", ".join(holds(disk))
            print(f"  {describe(disk)}: left alone ({what})")
            continue
        question = f"Erase and encrypt {describe(disk)} for data? [y/N] "
        if not yes(question, default=False):
            continue
        taken = {volume.mount for volume in chosen}
        number = len(chosen) + 1
        default = "/data" if number == 1 else f"/data{number}"
        mount = ask("Mount it at", default, mount_point(taken))
        if yes(f"Erase everything on {disk['name']}? [y/N] ", default=False):
            chosen.append(DataDisk(disk["name"], mount))
    return chosen


def erased() -> set[str]:
    """The disks an earlier attempt from this live ISO erased for data."""
    return set(ERASED.read_text().split()) if ERASED.exists() else set()


def close_leftovers(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close the encrypted volumes an earlier attempt left open (the live
    ISO opens none itself), so their disks can be erased again; lsblk's list
    again if any was."""
    opened = [
        device["name"]
        for disk in found
        for device in descendants(disk)
        if device["type"] == "crypt" and not in_use(device)
    ]
    for name in opened:
        run("cryptsetup", "close", name)
    return devices() if opened else found


def descendants(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything under a device in lsblk's tree."""
    found = []
    for child in device.get("children", []):
        found += [child, *descendants(child)]
    return found


def holds(device: dict[str, Any]) -> list[str]:
    """The partition table and file systems on a device, if any."""
    found = [kind for key in ("pttype", "fstype") if (kind := device.get(key))]
    for child in device.get("children", []):
        found += [kind for kind in holds(child) if kind not in found]
    return found


def mount_point(taken: set[str]) -> Callable[[str], bool]:
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


def targets(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the unused disks the system fits on from lsblk's --bytes list."""
    return [
        device
        for device in found
        if device["type"] == "disk"
        and device["size"] >= MIN_DISK_GIB * 2**30
        and not in_use(device)
    ]


def in_use(device: dict[str, Any]) -> bool:
    """Whether anything on a device is mounted."""
    children = device.get("children", [])
    return any(device["mountpoints"]) or any(map(in_use, children))


def partition(disk: str) -> tuple[str, str]:
    """GPT: the EFI system partition and the root. Returns their nodes."""
    layout = f"label: gpt\nsize=1GiB, type=uefi\ntype={ROOT_TYPE}\n"
    wipe = ["--wipe", "always", "--wipe-partitions", "always"]
    run("sfdisk", *wipe, disk, data=layout)
    run("udevadm", "settle")
    table = json.loads(output("sfdisk", "--json", disk))["partitiontable"]
    esp, root = (part["node"] for part in table["partitions"])
    return esp, root


def encrypt(part: str, name: str, passphrase: str) -> str:
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
        part,
        data=passphrase,
    )
    run("cryptsetup", "open", *key, part, name, data=passphrase)
    return luks


def make_data_disk(volume: DataDisk, passphrase: str) -> tuple[str, str]:
    """Erase a data disk: one partition, LUKS2 opened by a key file of its
    own or the passphrase, and Btrfs. Returns the LUKS and Btrfs UUIDs."""
    with ERASED.open("a") as record:
        record.write(f"{volume.disk}\n")
    wipe = ["--wipe", "always", "--wipe-partitions", "always"]
    run("sfdisk", *wipe, volume.disk, data=f"label: gpt\ntype={DATA_TYPE}\n")
    run("udevadm", "settle")
    table = json.loads(output("sfdisk", "--json", volume.disk))
    part = table["partitiontable"]["partitions"][0]["node"]
    luks = encrypt(part, volume.name, passphrase)
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
        part,
        key,
        data=passphrase,
    )
    run("cryptsetup", "config", "--key-slot=1", "--priority=prefer", part)
    filesystem = str(uuid.uuid4())
    run(
        "mkfs.btrfs",
        "--force",
        f"--uuid={filesystem}",
        f"/dev/mapper/{volume.name}",
    )
    return luks, filesystem
