# Jupiter-nixos

Installs NixOS with Hyprland, Quickshell and [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles): a flake whose modules declare the desktop, and three phases in Python with nothing beyond its standard library for what a configuration cannot do.

The NixOS counterpart of [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer), which installs the same desktop on Arch; [Jupiter-testing](https://github.com/skullduggerry/Jupiter-testing) lints and tests all of them. **Work in progress:** this started as a branch of Jupiter-installer and is not yet installed end to end; [docs/nixos.md](docs/nixos.md) says what works, how it was checked and what is left.

## Installing

As on Arch, for the TPM to unlock the disk at boot, erase the Secure Boot keys in the firmware's setup (Setup Mode) before booting the ISO, and phase 1 enrols the system's own, Microsoft's beside them. Without a TPM or Secure Boot, the disk asks for its passphrase at boot. The Arch installer's README says what the TPM's unlock leaves to you: a password on the firmware's setup, and firmware updates.

Boot the [NixOS ISO](https://nixos.org/download/) (minimal is enough) in UEFI mode and connect to the internet (`nmtui`). Then, as root (`sudo -i`):

```bash
curl -fsSL https://raw.githubusercontent.com/skullduggerry/Jupiter-nixos/main/bootstrap.sh | bash
```

This runs phase 1. It asks for your keyboard's layout first and loads it, then the disk to erase (no default where there is more than one), your user, time zone and locale, and installs. Reboot: the disk asks for its passphrase (until phase 3 binds it to the TPM). The login screen comes with phase 3, so log in on a text console (ctrl+alt+F2) as the user phase 1 created, and run the copy it left in your home, which updates itself and runs phases 2 and 3, then reboot:

```bash
~/Jupiter-nixos/bootstrap.sh
```

## Phases

| Phase | What |
|---|---|
| **1** | From the ISO: erases the disk you pick, Btrfs on LUKS2 (unless you decline), other empty disks as encrypted data disks if you choose them; writes your machine's `hosts/<hostname>/` and runs `nixos-install` from the flake, with Secure Boot keys of your own |
| **2** | `nixos-rebuild switch` from this repo: run it after changing `nixos/` or your settings, and to update |
| **3** | The dotfiles: cloned and linked into place, your theme on the login screen, a fingerprint where there is a reader, an unencrypted login keyring on an encrypted disk; last, the TPM bound to unlock the disk, or what is still missing for it. Safe to run again |

The desktop, your packages, the login screen and its PAM stacks, the finger in sudo and polkit and zsh are the flake's: `nixos/`.

## Customising

Fork this repo and the dotfiles, change `nixos/packages.nix`, point `flake.nix`'s `dotfiles` input and `jupiter_nixos/config.py` at your fork, and commit your `hosts/<hostname>/`. Leave the rest of `nixos/` as it is, and upstream's updates merge cleanly.

## Development

```bash
./check.sh                                    # lint and test this repo (--fix formats first)
./check.sh check all                          # every Jupiter repo
nix eval .#nixosConfigurations.example.config.system.build.toplevel.drvPath
```

The linters and tests live in Jupiter-testing, which `check.sh` clones next to this repo if it is missing.

## Documentation

- [docs/nixos.md](docs/nixos.md): the design, every step of the Arch installer and where it went, what NixOS made different, packages, status and roadmap.
- [The wiki](https://github.com/skullduggerry/Jupiter-dotfiles/wiki), shared by the Jupiter repos, for the desktop itself.
