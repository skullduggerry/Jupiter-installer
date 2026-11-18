# Jupiter-installer

Installs Arch Linux or NixOS with Hyprland, Quickshell and [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), in four phases written in plain Python. It tells which system it is on and refuses any other. On Arch the phases install with pacman and paru; on NixOS a flake declares the system and the phases build it. [Jupiter-testing](https://github.com/skullduggerry/Jupiter-testing) lints and tests both.

## Before installing

- **Secure Boot keys:** for the TPM to unlock the disk at boot, erase the firmware's Secure Boot keys (Setup Mode) before booting the ISO. Phase 1 then enrols the system's own, with Microsoft's and the firmware maker's beside them. If you skip this, phase 4 says what is left. Without a TPM or Secure Boot, the disk asks for its passphrase at every boot.
- **A firmware password:** the TPM opens the disk for this system's signed kernel image without a PIN, so the login screen guards your files. Without a password on the firmware's setup, anyone can turn Secure Boot off and boot a fake passphrase prompt.
- **Firmware updates** (`fwupdmgr refresh && fwupdmgr update`) carry the list of revoked boot loaders. If the disk asks for its passphrase after one, run phase 4 again to bind it once more.

## Installing

Boot the [Arch ISO](https://archlinux.org/download/) or the [NixOS ISO](https://nixos.org/download/) (minimal is enough) in UEFI mode, get online (`iwctl` on Arch, `nmtui` on NixOS), and run as root (`sudo -i` on NixOS):

```bash
curl -fsSL https://raw.githubusercontent.com/skullduggerry/Jupiter-installer/main/bootstrap.sh | bash
```

Phase 1 asks for your keymap first, so passwords are typed as they will be at boot. Where several disks could take the system it shows what each holds and has no default: type the one to erase. No password is written to a file.

Then reboot. The disk asks for its passphrase until phase 4 binds it to the TPM. Log in on the text console (ctrl+alt+F2 on NixOS) as your user and run the copy phase 1 left in your home:

```bash
~/Jupiter-installer/bootstrap.sh
```

That runs phases 3 and 4. The Wi-Fi the ISO joined is joined again; if not, connect with `nmtui` first. Reboot once more for the login screen. Already on Arch? Clone this repo and run `bootstrap.sh 2 3 4` as your user. NixOS is newer here than Arch: [docs/nixos.md](docs/nixos.md) says what is not yet tried on hardware.

## Phases

| Phase | Arch | NixOS |
|---|---|---|
| **1** | From the ISO: the chosen disk erased, Btrfs on LUKS2 (unless declined), optional encrypted data disks; pacstrap, systemd-boot with a signed unified kernel image, zram swap, GPU drivers, your user | From the ISO: the same questions and disks; `hosts/<hostname>/` written, then `nixos-install` from the flake (lanzaboote signs) |
| **2** | The desktop: `arch/packages/core.txt` and its services | `nixos-rebuild switch`: `nixos/desktop.nix` |
| **3** | Your packages: `arch/packages/pacman.txt` (enabling [multilib] if one needs it) and `aur.txt` through paru | The same rebuild: `nixos/packages.nix` |
| **4** | The dotfiles cloned and linked; as root, the login screen, udev rules, a finger for sudo and polkit, zsh | The dotfiles cloned and linked; the root half is declared by the flake |

Both phase 4s then keep the login keyring unencrypted on an encrypted disk (so a finger can log in), offer to enrol a fingerprint, and bind the TPM, or say what is still missing for it. Every phase can run again: 2 and 3 to update, 4 to update the dotfiles. On Arch a package that fails is skipped and named at the end. Every step in detail: the [Installing](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installing) wiki page.

## Customising

Fork this repo and the dotfiles, and point `bootstrap.sh` and `jupiter/config.py` at your forks (or set `INSTALLER_REPO`, `DOTFILES_REPO`, `DOTFILES_PUSH_URL`, `TESTING_REPO`). Then add your packages to `arch/packages/pacman.txt` and `aur.txt`, or on NixOS to `nixos/packages.nix`, point `flake.nix`'s `dotfiles` input at your fork and commit your `hosts/<hostname>/`. Leave the rest as it is, and upstream's updates merge cleanly. More in [Customising](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Customising).

## Development

```bash
./check.sh                                    # lint and test this repo (--fix formats first)
./check.sh check all                          # all three repos (./check.sh --help)
../Jupiter-testing/scripts/install-hooks.sh   # once: check on every commit and push
```

`check.sh` clones Jupiter-testing next to this repo if it is missing. The NixOS evaluations need Nix. [AGENTS.md](AGENTS.md) maps the code and its rules.

## Documentation

- [The wiki](https://github.com/skullduggerry/Jupiter-dotfiles/wiki), shared by the three repos: each phase step by step, [installer troubleshooting](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installer-troubleshooting) (every message and what to do), and [disk encryption](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Disk-encryption) (how the disk, Secure Boot, the TPM and the fingerprint fit together).
- [Jupiter on NixOS](docs/nixos.md): how it maps onto Arch's phases and what is still to do.
- [Encrypting an existing install](docs/encrypt-an-existing-install.md) (Arch), in place from the live ISO.
