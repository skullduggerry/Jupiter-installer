# Jupiter-installer

Installs Arch Linux or NixOS with Hyprland, Quickshell and [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), in four phases written in Python with nothing beyond its standard library. It tells which system it runs on (`/etc/os-release`, the ISO's own mark) and refuses any other: on Arch the phases install with pacman, on NixOS a flake (`nixos/`) declares the system and the phases build it. [docs/nixos.md](docs/nixos.md) says how the NixOS side maps onto Arch's, and what of it is not yet tried on hardware.

Part of Jupiter: [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles) is the desktop it sets up, and [Jupiter-testing](https://github.com/skullduggerry/Jupiter-testing) lints and tests both.

## Installing

Both systems are set up alike, and the same holds for each. For the TPM to unlock the disk at boot, Secure Boot needs keys of the system's own: before booting the ISO, erase the Secure Boot keys in the firmware's setup (Setup Mode), and phase 1 enrols the new ones, Microsoft's beside them. Phase 1 says so if the firmware is not in Setup Mode; you can go on, and phase 4 tells you what is left. Without a TPM or Secure Boot, the disk asks for its passphrase at boot.

The TPM gives the key to this system's signed kernel image and to nothing else, with no PIN: what then stands between someone holding the computer and its files is the login screen. Two things are yours to add. A password on the firmware's setup, without which anyone can turn Secure Boot off there and start a program that asks for your passphrase as the real prompt does; the real one only appears after a firmware update, and phase 4 then binds the disk again. And firmware updates (`fwupdmgr refresh && fwupdmgr update`, from phase 3's fwupd), which carry the list of boot loaders Microsoft has withdrawn its signature from.

Boot the [Arch ISO](https://archlinux.org/download/) in UEFI mode and connect to the internet (`iwctl` for Wi-Fi). Then, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/skullduggerry/Jupiter-installer/main/bootstrap.sh | bash
```

This runs phases 1 and 2. It asks for your keyboard's layout first and loads it, so your passwords are typed as you will type them at boot. Where more than one disk could take the system it shows what each holds and has no default: type the one to erase. Reboot: the disk asks for its passphrase (until phase 4 binds it to the TPM), and a text console asks you to log in, since the login screen comes with phase 4. Log in as the user phase 1 created and run the copy it left in your home, which updates itself and runs phases 3 and 4. They need the network: the Wi-Fi the live ISO joined is joined again, and if there is none they stop and say to connect with `nmtui`:

```bash
~/Jupiter-installer/bootstrap.sh
```

Already on Arch? Clone this repo and run `bootstrap.sh 2 3 4` as your user. Any phase can be run again later, e.g. `bootstrap.sh 4` to update the dotfiles.

### On NixOS

Boot the [NixOS ISO](https://nixos.org/download/) (minimal is enough) in UEFI mode, connect with `nmtui`, then as root (`sudo -i`) run the same `curl … | bash` line. Phase 1 asks the same questions and lays the disk out the same way, then writes your machine's `hosts/<hostname>/` (its answers and hardware) into the copy of this repo it leaves in your home and installs from the flake. Reboot; until phase 4 installs the login screen, log in on a text console (ctrl+alt+F2) and run `~/Jupiter-installer/bootstrap.sh`, then reboot again. Passwords never go into the configuration, which ends up in the world-readable store.

## Phases

| Phase | On Arch | On NixOS |
|---|---|---|
| **1** | The base system, from the live ISO: erases the disk you pick, then Btrfs (on LUKS2 unless you decline), systemd-boot with a signed kernel image and Secure Boot keys of your own, swap on zram, drivers for your GPUs and your user; other empty disks only if you choose them, as encrypted data disks | | From the NixOS ISO, the same disk layout and questions; then `hosts/<hostname>/` and `nixos-install` from the flake, Secure Boot keys of your own made first (lanzaboote) |
| **2** | The desktop: `packages/core.txt` and the services it needs | | `nixos-rebuild switch`: the desktop is `nixos/desktop.nix` |
| **3** | Your own packages: `packages/pacman.txt` (with [multilib] enabled where one needs it, such as steam), and `packages/aur.txt` through paru, with pacman's `Color`, `ILoveCandy` and `VerbosePkgLists` turned on for both. Where ufw is installed it gets KDE Connect's rules; turning it on is yours: `sudo ufw enable` | | The same rebuild, once a run with phase 2: your packages are `nixos/packages.nix`; KDE Connect's ports are open to local networks in NixOS's firewall, which is on |
| **4** | The dotfiles: cloned and linked into place, with the login screen, an unencrypted login keyring on an encrypted disk, a fingerprint where there is a reader (login screen, sudo, polkit) and zsh; last, the TPM bound to unlock the disk, or what is still missing for it. Safe to run again | | The same as on Arch, but what Arch installs as root here (greetd and its PAM stacks, udev, the finger in sudo and polkit, zsh) the flake declares |

A package that fails to install is skipped, and named again at the end. Run phases 2 and 3 again to update the system, 4 to update the dotfiles, on either. What each phase does in detail: [Installing](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installing).

## Customising

Both this installer and the dotfiles are meant to be forked: add your packages to `packages/pacman.txt` and `aur.txt` (Arch) or `nixos/packages.nix` (NixOS), and point `bootstrap.sh`, `jupiter/config.py` and, for NixOS, `flake.nix`'s `dotfiles` input at your forks (or set `INSTALLER_REPO`, `DOTFILES_REPO`, `DOTFILES_PUSH_URL` and `TESTING_REPO`). On NixOS, commit your machine's `hosts/<hostname>/` to your fork. Leave the rest of `jupiter/` and `nixos/` as it is, and upstream's updates merge cleanly. More in [Customising](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Customising).

## Development

```bash
./check.sh                                    # lint and test this repo (--fix formats first)
./check.sh check all                          # all three: dotfiles, installer, testing
./check.sh lint dotfiles                      # or test: one half, one repo (./check.sh --help)
../Jupiter-testing/scripts/install-hooks.sh   # once: check on every commit and push
```

Each Jupiter repo has this `check.sh`, with the same arguments, and `bootstrap.sh check|lint|test` runs it too. The linters and tests live in Jupiter-testing, which it clones next to this repo if it is missing. The tools they need are in `packages/pacman.txt`.

## Documentation

- [The wiki](https://github.com/skullduggerry/Jupiter-dotfiles/wiki), shared by the three repos: installing, customising, development.
- Every step of each phase, in the order it happens: [phase 1](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-1-Base-system), [phase 2](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-2-Desktop), [phase 3](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-3-Packages), [phase 4](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Phase-4-Dotfiles).
- [Installer troubleshooting](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Installer-troubleshooting): every message the installer prints, what it means and what to do.
- [Disk encryption](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Disk-encryption): how the encrypted disk, Secure Boot, the TPM and the fingerprint fit together, and a checklist for real hardware with the way back from each step.
- [Encrypting an existing install](docs/encrypt-an-existing-install.md): a system phase 1 installed before it encrypted, encrypted in place from the live ISO.
- [Jupiter on NixOS](docs/nixos.md): how the NixOS side maps onto Arch's phases, what NixOS made different, its packages, its known issues, and what is not yet tried on hardware.
- [AGENTS.md](AGENTS.md): the map and the rules of the code, for coding agents (Claude Code reads it through `CLAUDE.md`).
