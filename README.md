# Jupiter-installer

Installs Arch Linux or NixOS with Hyprland, Quickshell and [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), in four phases written in Python with nothing beyond its standard library. It tells which system it runs on (`/etc/os-release`, the ISO's own mark) and refuses any other. On Arch the phases install with pacman and paru; on NixOS a flake declares the system and the phases build it.

Part of Jupiter: [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles) is the desktop it sets up, and [Jupiter-testing](https://github.com/skullduggerry/Jupiter-testing) lints and tests both.

## What is where

Every path belongs to one of three parts. What both systems do the same is written once; the Arch and NixOS parts hold only what differs, and neither uses the other.

**Shared by both**

| Path | What |
| --- | --- |
| `bootstrap.sh` | the `curl … \| bash` entry: fetches or updates this repo, runs `python3 -m jupiter` |
| `jupiter/__main__.py`, `distro.py` | which system this is, and which phases run |
| `jupiter/questions.py`, `disks.py` | phase 1's questions, and its disks: the system's, LUKS2, data disks |
| `jupiter/dotfiles.py` | phase 4's start: the dotfiles cloned, linked, their first theme |
| `jupiter/secureboot.py`, `tpm.py`, `keyring.py` | Secure Boot keys, the TPM unlocking the disk, the login keyring |
| `jupiter/common.py`, `config.py` | running commands; where the dotfiles come from |
| `check.sh`, `docs/` | the checks; the documentation |

**Arch only**

| Path | What |
| --- | --- |
| `jupiter/arch/` | the four phases: pacstrap and arch-chroot, pacman, paru, the root files |
| `arch/packages/` | the package lists: `core.txt` (phase 2), `pacman.txt` and `aur.txt` (phase 3) |

**NixOS only**

| Path | What |
| --- | --- |
| `jupiter/nixos/` | the phases: `nixos-install`, `nixos-rebuild`, and what a configuration cannot do |
| `flake.nix`, `flake.lock`, `nixos/` | the system, declared: desktop, packages, login, Secure Boot, theme |
| `hosts/<hostname>/` | one machine: phase 1's answers and its hardware |

## Before installing (both)

For the TPM to unlock the disk at boot, Secure Boot needs keys of the system's own: before booting the ISO, erase the Secure Boot keys in the firmware's setup (Setup Mode), and phase 1 enrols the new ones, Microsoft's beside them. Phase 1 says so if the firmware is not in Setup Mode; you can go on, and phase 4 tells you what is left. Without a TPM or Secure Boot, the disk asks for its passphrase at boot.

The TPM gives the key to this system's signed kernel image and to nothing else, with no PIN: what then stands between someone holding the computer and its files is the login screen. Two things are yours to add. A password on the firmware's setup, without which anyone can turn Secure Boot off there and start a program that asks for your passphrase as the real prompt does; the real one only appears after a firmware update, and phase 4 then binds the disk again. And firmware updates (`fwupdmgr refresh && fwupdmgr update`), which carry the list of boot loaders Microsoft has withdrawn its signature from.

Both start from their own ISO with the same line, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/skullduggerry/Jupiter-installer/main/bootstrap.sh | bash
```

Phase 1 asks for your keyboard's layout first and loads it, so your passwords are typed as you will type them at boot. Where more than one disk could take the system it shows what each holds and has no default: type the one to erase. Passwords never go into a file the installer writes.

## Installing on Arch

Boot the [Arch ISO](https://archlinux.org/download/) in UEFI mode, connect to the internet (`iwctl` for Wi-Fi), and run the line above. It runs phases 1 and 2. Reboot: the disk asks for its passphrase (until phase 4 binds it to the TPM), and a text console asks you to log in, since the login screen comes with phase 4. Log in as the user phase 1 created and run the copy it left in your home, which updates itself and runs phases 3 and 4. They need the network: the Wi-Fi the live ISO joined is joined again, and if there is none they stop and say to connect with `nmtui`:

```bash
~/Jupiter-installer/bootstrap.sh
```

Already on Arch? Clone this repo and run `bootstrap.sh 2 3 4` as your user.

## Installing on NixOS

Boot the [NixOS ISO](https://nixos.org/download/) (minimal is enough) in UEFI mode, connect with `nmtui`, then run the line above as root (`sudo -i`). Phase 1 asks the same questions and lays the disk out the same way, then writes your machine's `hosts/<hostname>/` (its answers and hardware) into the copy of this repo it leaves in your home and installs from the flake. Reboot; until phase 4 installs the login screen, log in on a text console (ctrl+alt+F2) and run `~/Jupiter-installer/bootstrap.sh`, then reboot again. NixOS is newer here than Arch: [docs/nixos.md](docs/nixos.md) says what of it is not yet tried on hardware.

## Phases

| Phase | On Arch | On NixOS |
|---|---|---|
| **1** | From the ISO: the disk you pick erased, Btrfs (on LUKS2 unless you decline), other empty disks as encrypted data disks only if you choose them; then pacstrap, systemd-boot with a signed kernel image and Secure Boot keys of your own, swap on zram, drivers for your GPUs, your user | From the ISO: the same questions and disks; then `hosts/<hostname>/` and `nixos-install` from the flake, Secure Boot keys of your own made first (lanzaboote) |
| **2** | The desktop: `arch/packages/core.txt` and the services it needs | `nixos-rebuild switch`: the desktop is `nixos/desktop.nix` |
| **3** | Your packages: `arch/packages/pacman.txt` (with [multilib] where one needs it, such as steam) and `aur.txt` through paru, with pacman's `Color`, `ILoveCandy` and `VerbosePkgLists`. Where ufw is installed it gets KDE Connect's rules; turning it on is yours: `sudo ufw enable` | The same rebuild, once a run with phase 2: your packages are `nixos/packages.nix`; KDE Connect's ports are open to local networks in NixOS's firewall, which is on |
| **4** | The dotfiles cloned and linked, then installed as root: the login screen, udev rules, the finger in sudo and polkit, zsh | The dotfiles cloned and linked; what Arch installs as root the flake declares |

Both phase 4s then keep an unencrypted login keyring on an encrypted disk, enrol a fingerprint where there is a reader, and last bind the TPM to unlock the disk, or say what is still missing for it. Any phase can be run again: 2 and 3 to update the system, 4 to update the dotfiles (`bootstrap.sh 4`). On Arch, a package that fails to install is skipped and named again at the end. Every step in detail: [Installing](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installing).

## Customising

This installer and the dotfiles are meant to be forked. On either system, point `bootstrap.sh` and `jupiter/config.py` at your forks (or set `INSTALLER_REPO`, `DOTFILES_REPO`, `DOTFILES_PUSH_URL` and `TESTING_REPO`). Then:

- **Arch:** add your packages to `arch/packages/pacman.txt` and `aur.txt`.
- **NixOS:** add them to `nixos/packages.nix`, point `flake.nix`'s `dotfiles` input at your fork, and commit your machine's `hosts/<hostname>/`.

Leave the rest of `jupiter/` and `nixos/` as it is, and upstream's updates merge cleanly. More in [Customising](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Customising).

## Development

```bash
./check.sh                                    # lint and test this repo (--fix formats first)
./check.sh check all                          # all three: dotfiles, installer, testing
./check.sh lint dotfiles                      # or test: one half, one repo (./check.sh --help)
../Jupiter-testing/scripts/install-hooks.sh   # once: check on every commit and push
```

Each Jupiter repo has this `check.sh`, with the same arguments, and `bootstrap.sh check|lint|test` runs it too. The linters and tests live in Jupiter-testing, which it clones next to this repo if it is missing; they cover both systems on any machine, and the NixOS evaluations need Nix. On Arch, the tools they need are in `arch/packages/pacman.txt`.

## Documentation

- **Both:** [the wiki](https://github.com/skullduggerry/Jupiter-dotfiles/wiki), shared by the three repos (installing, customising, development); every step of each phase in order: [phase 1](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-1-Base-system), [phase 2](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-2-Desktop), [phase 3](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-3-Packages), [phase 4](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-4-Dotfiles); [installer troubleshooting](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installer-troubleshooting), every message it prints and what to do; [disk encryption](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Disk-encryption), how the disk, Secure Boot, the TPM and the fingerprint fit together, with a checklist for real hardware.
- **Arch:** [encrypting an existing install](docs/encrypt-an-existing-install.md), a system phase 1 installed before it encrypted, encrypted in place from the live ISO.
- **NixOS:** [Jupiter on NixOS](docs/nixos.md): how it maps onto Arch's phases, what NixOS made different, the theme, updates, packages, and what is not yet tried on hardware.
- **Code:** [AGENTS.md](AGENTS.md), the map and the rules, for coding agents (Claude Code reads it through `CLAUDE.md`).
