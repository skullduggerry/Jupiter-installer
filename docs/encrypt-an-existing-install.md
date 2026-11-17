# Encrypting an existing install (Arch)

Phase 1 encrypts a new install. A system phase 1 installed before it did
(Btrfs straight on its partition, a loader entry with a separate initramfs)
can be encrypted where it is, from the live ISO, without reinstalling: its
Btrfs is shrunk a little, `cryptsetup reencrypt` encrypts the partition in
place, and the boot is set up as phase 1 sets up a new one. Then phase 4
binds the disk to the TPM, as on a new install.

This rewrites every block of the partition. A power cut or crash midway can
be resumed (`cryptsetup reencrypt --resume-only`), but have a backup of
everything you care about before you start, on another disk, and test that
you can read it. Plan for the time it takes: about as long as reading and
writing the whole partition once.

The commands below are tested as written (Jupiter-testing's
`vm/test_install.Converted` runs every block of this file in a VM). They
assume phase 1's layout: the EFI system partition first, the root partition
second. Run them as root on the live ISO, booted in UEFI mode, with your
keyboard layout loaded (`loadkeys`) so the passphrase is typed as it will be
at boot.

## 1. Find the partitions

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
```

Set `DISK` to the disk the system is on, then check that the second
partition is the Btrfs root and the first the vfat ESP:

```bash
DISK=/dev/nvme0n1
ESP=$(lsblk -lnpo NAME "$DISK" | sed -n 2p)
ROOT=$(lsblk -lnpo NAME "$DISK" | sed -n 3p)
lsblk -no NAME,FSTYPE "$ESP" "$ROOT"
```

The second line must say `btrfs`, the first `vfat`. Stop if they do not.

## 2. Make room for the LUKS header

LUKS2 keeps its header (16 MiB) at the start of the partition, so the file
system gives up 32 MiB at its end first:

```bash
mount "$ROOT" /mnt
btrfs filesystem resize -32M /mnt
umount /mnt
```

## 3. Encrypt in place

Answer `YES` to its warning, then type the passphrase you will type at boot
(twice). This is the long step:

```bash
cryptsetup reencrypt --encrypt --type luks2 --reduce-device-size 32M "$ROOT"
```

## 4. Open it and give the file system its room back

```bash
cryptsetup open "$ROOT" root
mount -o subvol=@ /dev/mapper/root /mnt
btrfs filesystem resize max /mnt
mount -o subvol=@home /dev/mapper/root /mnt/home
mount -o subvol=@log /dev/mapper/root /mnt/var/log
mount -o subvol=@pkg /dev/mapper/root /mnt/var/cache/pacman/pkg
mount "$ESP" /mnt/boot
```

## 5. Boot it as phase 1 boots a new install

The root is opened in systemd's initramfs (crypttab's `x-initrd.attach`),
its passphrase asked in your console keymap (`sd-vconsole`), and the kernel
is started as one signed image with its command line in it, from the loader
entry's, with the root named by its opened volume instead of its file
system's UUID (a disk without encryption could carry that UUID, and be
mounted in the root's place):

```bash
cat >/mnt/etc/crypttab <<EOF
root UUID=$(cryptsetup luksUUID "$ROOT") none discard,x-initrd.attach,tpm2-measure-pcr=yes
EOF
echo 'HOOKS=(systemd keyboard autodetect microcode modconf sd-vconsole block sd-encrypt filesystems)' \
    >/mnt/etc/mkinitcpio.conf.d/jupiter.conf
mkdir -p /mnt/etc/kernel
sed -n 's/^options *//p' /mnt/boot/loader/entries/arch.conf |
    sed 's|root=UUID=[^ ]*|root=/dev/mapper/root|' >/mnt/etc/kernel/cmdline
cat >/mnt/etc/mkinitcpio.d/linux.preset <<'EOF'
ALL_kver="/boot/vmlinuz-linux"
PRESETS=('default')
default_uki="/boot/EFI/Linux/arch-linux.efi"
EOF
```

Check that `/mnt/etc/kernel/cmdline` names `root=/dev/mapper/root` and
`rootflags=subvol=@`:

```bash
cat /mnt/etc/kernel/cmdline
```

Then Secure Boot keys of the system's own, enrolled now if the firmware is
in Setup Mode (phase 4 enrols them later otherwise), systemd-boot signed,
the image built and signed, and the old loader entry and initramfs gone:

```bash
arch-chroot /mnt pacman -S --needed --noconfirm sbctl tpm2-tss
arch-chroot /mnt sbctl create-keys
if [ "$(od -An -tu1 -j4 /sys/firmware/efi/efivars/SetupMode-* 2>/dev/null | tr -d ' ')" = 1 ]; then
    arch-chroot /mnt sbctl enroll-keys --microsoft
fi
arch-chroot /mnt sbctl sign --save \
    --output /usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed \
    /usr/lib/systemd/boot/efi/systemd-bootx64.efi
arch-chroot /mnt bootctl install
rm /mnt/boot/loader/entries/arch.conf /mnt/boot/initramfs-linux*.img
arch-chroot /mnt mkinitcpio --allpresets
arch-chroot /mnt systemctl enable systemd-boot-update.service
```

Phase 2 turned systemd's TPM measurements off on the unencrypted system;
the TPM binding needs them:

```bash
arch-chroot /mnt systemctl unmask systemd-tpm2-setup-early.service \
    systemd-tpm2-setup.service systemd-pcrphase-initrd.service \
    systemd-pcrphase-sysinit.service systemd-pcrphase.service \
    systemd-pcrmachine.service systemd-pcrproduct.service \
    systemd-pcrlogin@.service systemd-pcrnvdone.service \
    systemd-pcrosseparator.service
```

## 6. Reboot, then bind the TPM

```bash
umount -R /mnt
cryptsetup close root
reboot
```

The disk asks for its passphrase. If the firmware was not in Setup Mode,
erase its Secure Boot keys in its setup first (or after: phase 4 says what
is left). Log in and run phase 4, which enrols the keys if it can, binds the
disk to the TPM once Secure Boot is on, adds a recovery key and offers a
header backup:

```bash
~/Jupiter-installer/bootstrap.sh 4
```

## If something goes wrong

- Interrupted during step 3: boot the ISO again and run
  `cryptsetup reencrypt --resume-only "$ROOT"`.
- It does not boot after step 6: boot the ISO, `cryptsetup open "$ROOT"
  root`, mount as in step 4, and look at what step 5 wrote; `arch-chroot
  /mnt mkinitcpio --allpresets` shows what the image lacks.
- To go back, restore the backup you made before step 2: decrypting in
  place is possible (cryptsetup-reencrypt(8)) but untested here.
