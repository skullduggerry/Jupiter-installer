# Jupiter Installer

Installer for [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles), as well as my own preferred setup for Arch Linux: Hyprland and Quickshell on top of a plain Arch install.

It runs in four phases, written in Python with nothing beyond its standard library.

## Usage

Boot the [Arch ISO](https://archlinux.org/download/) in UEFI mode and connect to the internet (`iwctl` for Wi-Fi). If your keyboard is not US, load its layout with `loadkeys` first, so your passwords are typed the way you will type them later. Then, as root:

```bash
curl -fsSL https://codeberg.org/skullduggery/Jupiter-installer/raw/branch/main/bootstrap.sh | bash
```

This runs phases 1 and 2. Reboot, log in as the user phase 1 created and run the copy of the installer it left in your home, which updates itself and runs phases 3 and 4:

```bash
~/Jupiter-installer/bootstrap.sh
```

Any phase can be run on its own later, e.g. `~/Jupiter-installer/bootstrap.sh 4` to update the dotfiles. In a clone, `python3 -m jupiter [phase ...]` runs phases without updating first.

## Phases

| Phase | Description |
|---|---|
| **1** | The base system, from the live ISO. Erases the disk you pick and follows the Arch Installation guide with archinstall's defaults: GPT with a 1 GiB EFI system partition at `/boot`, Btrfs with `@`, `@home`, `@log` and `@pkg` subvolumes (zstd compressed), swap on zram, systemd-boot, NetworkManager, CPU microcode, graphics drivers for the GPUs it finds (`nvidia-open` and `libva-nvidia-driver` for NVIDIA Turing and newer, plus the session variables Hyprland's wiki asks for when that is the only GPU) and your user with sudo. The keymap you pick is also the desktop's and the login screen's keyboard layout, as `localectl set-keymap` would make it. Skip it if you install Arch by hand or with `archinstall`. |
| **2** | The desktop, `packages/core.txt`: Hyprland (started through uwsm), Quickshell, PipeWire, greetd and the apps the dotfiles use. Enables NetworkManager, Bluetooth, power-profiles-daemon, reflector's weekly mirrorlist refresh, the Wi-Fi rules of your time zone's country, the polkit agent and the SSH agent (gcr-ssh-agent). From the ISO it installs into `/mnt`, on an installed system through sudo. |
| **3** | Your own packages: `packages/pacman.txt` with pacman and `packages/aur.txt` with paru, which is built first if it is missing. It shows paru's own PKGBUILD and asks before building it; paru then shows every package's PKGBUILD for review before building it. `aur.txt` starts with `wallust`, which the dotfiles' theming needs. Where ufw is installed, it lets KDE Connect in from local networks (its own `KDEConnect` profile, for the private address ranges only). |
| **4** | The dotfiles: clones them into your home and links every folder of their `.config/` into `~/.config/` and `.zshrc` into `~`, moving whatever was in the way to `~/.dotfiles-backup/<time>/`. Then masks other notification daemons, renders the theme, installs the dotfiles' udev rules and pacman hooks (`scripts/install-system.sh`), installs the login screen, enables greetd unless another display manager is enabled, and makes zsh your login shell. Where fprintd finds a fingerprint reader, it offers to enroll a finger and lets sudo take one; the lock screen takes it too, while logging in stays with the password, which unlocks the keyring. Safe to run again. |

A package that fails to install in phases 2 and 3, because it left the repositories or its AUR build broke, is skipped instead of stopping the install. The installer names it when it happens and again at the end, so you can install it later. Building paru takes about 4 GB of memory, swap included; if the build fails, for that or any other reason, phase 3 skips the AUR packages and names them too.

## Philosophy

The core concept is customization. Both the installer and the dotfiles are meant to be forked from `main` and adapted to your own needs - adding packages to the user-defined lists, tweaking dotfiles, or changing setup steps entirely. To install from your forks, change the URL in `bootstrap.sh` and the two in `jupiter/config.py`, or set `INSTALLER_REPO`, `DOTFILES_REPO` and `DOTFILES_PUSH_URL` in the environment. Phase 4 clones the dotfiles over HTTPS, which needs no keys, and pushes them over SSH.

It's recommended to leave installer-internal files (`jupiter/`, except `config.py`) unchanged unless you know what you're doing, to avoid merge conflicts when pulling upstream updates.

## Development

`scripts/check.sh` checks everything: ruff formats and lints the Python, mypy checks its types, shfmt and shellcheck do the shell, and the tests run under coverage. `--fix` formats first, it names any tool that is missing, and `scripts/install-hooks.sh`, run once per clone, has it run on every commit and push. The tools are in `packages/pacman.txt`, so phase 3 installs them.

The tests are a repo of their own, Jupiter-testing, cloned next to this one (or wherever `JUPITER_TESTING` points); `check.sh` runs this repo's share of them. They run phase 1 from the first question to the last file against stand-in commands and a temporary `/mnt`, and phases 2 to 4 the same way in a throwaway home, broken packages included. They also check the drivers phase 1 picks for Intel, AMD, NVIDIA, hybrid and virtual machines, that every official package the installer names exists, that no package is listed twice, and who phase 1 makes a user with which password and rights.
