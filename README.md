# Jupiter Installer

Installer for [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles), as well as my own preferred setup for Arch Linux.

`installer.sh` runs the Phases/Scrips as detailed below,also letting you choose which ones to run during or install.

## Usage

Clone the repo manually, or run it via curl. Using curl, run the two commands below in order — once from the Arch ISO, once after reboot.


```bash
# From the Arch ISO, as root
curl -fsSL https://codeberg.org/skullduggery/Jupiter-installer/raw/branch/main/bootstrap.sh | bash -s -- --only 1,2
```
```bash
# After reboot, as your normal user:
curl -fsSL https://codeberg.org/skullduggery/Jupiter-installer/raw/branch/main/bootstrap.sh | bash -s -- --only 3,4
```

## Philosophy

The core idea is **customization**. Both the installer and the dotfiles are meant to be forked from `main` and adapted to your own needs — adding packages to the user-defined list, tweaking dotfiles, or changing setup steps entirely. You simply modify the links in the config.sh and bootstrap.sh to be your fork. This can be done post or pre-install, assuming you have a system you can edit the your fork with.

It's recommended to leave installer-internal files unchanged unless you know what you're doing, to avoid merge conflicts when pulling upstream updates.

## Phases

| Phase | Description |
|---|---|
| **1** | system installation — drive configuration, driver setup, user account creation. Similar to `archinstall`. Can be skipped in favor of manual installation or `archinstall` itself. |
| **2** | Installs core components (Hyprland, Quickshell) and recommended programs (Neovim, etc.). |
| **3** | Installs user-defined packages (e.g. Steam), defined in `pacman.txt` and `AUR.txt`. |
| **4** | Sets up dotfiles — pulls from [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles) `main` by default. |
