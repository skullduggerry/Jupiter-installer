# Jupiter-installer

Installs Arch Linux with Hyprland, Quickshell and [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles), in four phases written in Python with nothing beyond its standard library.

Part of Jupiter: [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles) is the desktop it sets up, and [Jupiter-testing](https://codeberg.org/skullduggery/Jupiter-testing) lints and tests both.

## Installing

Boot the [Arch ISO](https://archlinux.org/download/) in UEFI mode and connect to the internet (`iwctl` for Wi-Fi). If your keyboard is not US, load its layout with `loadkeys` first, so your passwords are typed as you will type them later. Then, as root:

```bash
curl -fsSL https://codeberg.org/skullduggery/Jupiter-installer/raw/branch/main/bootstrap.sh | bash
```

This runs phases 1 and 2. Reboot, log in as the user phase 1 created, and run the copy it left in your home, which updates itself and runs phases 3 and 4:

```bash
~/Jupiter-installer/bootstrap.sh
```

Already on Arch? Clone this repo and run `bootstrap.sh 2 3 4` as your user. Any phase can be run again later, e.g. `bootstrap.sh 4` to update the dotfiles.

## Phases

| Phase | What |
|---|---|
| **1** | The base system, from the live ISO: erases the disk you pick, then Btrfs, systemd-boot, swap on zram, drivers for your GPUs and your user |
| **2** | The desktop: `packages/core.txt` and the services it needs |
| **3** | Your own packages: `packages/pacman.txt`, and `packages/aur.txt` through paru |
| **4** | The dotfiles: cloned and linked into place, with the login screen and zsh. Safe to run again |

A package that fails to install is skipped, and named again at the end. What each phase does in detail: [Installing](https://codeberg.org/skullduggery/Jupiter-dotfiles/wiki/Installing).

## Customising

Both this installer and the dotfiles are meant to be forked: add your packages to `packages/pacman.txt` and `aur.txt`, and point `bootstrap.sh` and `jupiter/config.py` at your forks (or set `INSTALLER_REPO`, `DOTFILES_REPO`, `DOTFILES_PUSH_URL` and `TESTING_REPO`). Leave the rest of `jupiter/` as it is, and upstream's updates merge cleanly. More in [Customising](https://codeberg.org/skullduggery/Jupiter-dotfiles/wiki/Customising).

## Development

```bash
./check.sh                                    # lint and test this repo (--fix formats first)
./check.sh check all                          # all three: dotfiles, installer, testing
./check.sh lint dotfiles                      # or test: one half, one repo (./check.sh --help)
../Jupiter-testing/scripts/install-hooks.sh   # once: check on every commit and push
```

Each Jupiter repo has this `check.sh`, with the same arguments, and `bootstrap.sh check|lint|test` runs it too. The linters and tests live in Jupiter-testing, which it clones next to this repo if it is missing. The tools they need are in `packages/pacman.txt`.

## Documentation

- [The wiki](https://codeberg.org/skullduggery/Jupiter-dotfiles/wiki), shared by the three repos: installing, customising, development.
