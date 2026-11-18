# Jupiter on NixOS

How the installer sets up the same desktop on NixOS as on Arch: what it
shares with the Arch side, what NixOS made different, and what is still to
do. One installer serves both: `jupiter/distro.py` tells which system it
runs on (archiso's mark, `VARIANT_ID=installer` on the NixOS ISO, `ID=` in
`/etc/os-release` once installed) and refuses any other, as phase 1 erases
disks. Jupiter-dotfiles serves both, and Jupiter-testing checks both.

## Overview

The Arch side is imperative: four Python phases run pacman, paru,
`arch-chroot` and `sudo` in order. On NixOS the system is a function of its
configuration, so everything that phase 2, phase 3 and the root half of
phase 4 do with packages and files is a NixOS module in `nixos/`, and what
remains imperative stays in Python, in `jupiter/nixos/`, built on the code
both systems share (the modules at the top of `jupiter/`) where the work is
the same, as `jupiter/arch/` is:

| | On Arch | On NixOS |
|---|---|---|
| Questions, disks, LUKS, data disks | phase 1 (`jupiter/questions.py`, `disks.py`) | phase 1, the same modules |
| Base system, boot, user, drivers | phase 1 (pacstrap, mkinitcpio, sbctl) | `nixos/base.nix`, `secureboot.nix`; phase 1 runs `nixos-install` |
| Desktop packages and services | phase 2 (`arch/packages/core.txt`) | `nixos/desktop.nix`, built by phases 2 and 3 |
| Your packages | phase 3 (`pacman.txt`, `aur.txt`) | `nixos/packages.nix`, the same build |
| Root files of the dotfiles, greetd, PAM, finger in sudo/polkit, zsh | phase 4 (`install-system.sh`, `install-greeter.sh`, `/etc/pam.d` edits, `chsh`) | `nixos/login.nix`, `base.nix` |
| Dotfiles linked into the home, theme, keyring, fingerprint, TPM | phase 4 | phase 4: the same linking (`jupiter/dotfiles.py`), keyring and TPM binding, with `jupiter/nixos/phase4.py` and `tpm.py` for the rest |
| Updating | `bootstrap.sh 2 3 4` (pacman -Syu, paru) | `bootstrap.sh 2 4` (git pull, `nixos-rebuild switch`) |

The phases on NixOS:

1. **Install**, as root from the NixOS ISO: Arch's questions, disk layout
   and encryption, then `hosts/<hostname>/settings.json` (the answers and
   what was found), `hardware-configuration.nix`
   (`nixos-generate-config --no-filesystems`), Secure Boot keys, and
   `nixos-install --flake` from the copy of this repo it leaves in the new
   home.
2. and 3. **The system**, as your user: one `nixos-rebuild switch --sudo
   --flake ~/Jupiter-installer#<host>` a run, whichever of the two is
   named. Run again after any change to `nixos/` or the settings, and to
   update.
4. **Dotfiles**, as your user: Arch's phase 4 minus what is declared.

`bootstrap.sh` runs 1 on the ISO and 3 4 otherwise, as on Arch.

## Layout

```
flake.nix                 nixpkgs (unstable), lanzaboote, home-manager, Stylix, the dotfiles (flake = false)
nixos/default.nix         options.jupiter: the settings' schema, and the imports
nixos/base.nix            boot, initrd crypttab, file systems, zram, user, locale, GPUs
nixos/secureboot.nix      lanzaboote, on an encrypted system
nixos/desktop.nix         core.txt: Hyprland (uwsm), Quickshell, PipeWire, keyring, fonts, ...
nixos/packages.nix        pacman.txt and aur.txt; the firewall's KDE Connect rules
nixos/login.nix           greetd, its PAM stacks, root's greeter copy, udev, drop-ins, /usr/share links
nixos/theme.nix           Stylix and home-manager: the console, fonts, btop, mpv, Zed; a specialisation per theme
nixos/desktop-entries.py  the dotfiles' uwsm-desktop-entries.py, run as the profile is built
hosts/<name>/             settings.json + hardware-configuration.nix, one per machine
jupiter/nixos/            the NixOS phases, on the code both systems share (jupiter/)
jupiter/distro.py         which system this is
```

Each machine is a folder of `hosts/`, and the flake makes
`nixosConfigurations.<folder>` of each. `settings.json` is JSON, not Nix,
so nothing typed in phase 1 can become code; `nixos/default.nix` types
every field (a hostname, a user name, a mount point by pattern), so a bad
value fails the evaluation rather than the boot. `hosts/example` is a
stand-in that the checks evaluate.

Passwords never enter the configuration: everything in it ends up in the
world-readable store. Phase 1 sets them with `chpasswd` on stdin inside
`nixos-enter`, and `users.mutableUsers` stays on.

## Differences from Arch

The dotfiles were written for Arch's file system. They now serve both
systems: where they can find a file by the system's own means they do
(`.zshrc`'s plugins on `XDG_DATA_DIRS`, the lock screen's reader in a stack
the system declares), and where a path is fixed in QML or CSS,
`nixos/login.nix` links it. Each change, on either side:

- **PAM modules by path.** NixOS's Linux-PAM finds only its own modules by
  name. The dotfiles' `etc/pam.d/greetd` and `greetd-greeter` are read from
  the flake's `dotfiles` input with `pam_fprintd.so` and
  `pam_gnome_keyring.so` replaced by store paths.
- **No `system-local-login`.** Arch's stack is replaced by
  `jupiter-local-login`, built from NixOS's options to match Arch's
  `system-auth`: pam_faillock around the password, and the password's line
  `[success=1 default=bad]` rather than NixOS's `sufficient`, which would
  end the including stack and skip the lines after the include (the
  keyring's, the finger count's reset). No gnome-keyring, no finger: the
  greetd stack decides both.
- **pam_exec's helpers.** `finger-asked` and `disk-encrypted` name their
  tools as `/usr/bin/...`, which NixOS lacks; a missing `tr` would read as
  an empty answer and send every password to the reader. They are built
  with their tools by store path, the build fails if one is left, and the
  stack names them by store path, not `/etc/greetd`.
- **greetd waits for the greeter.** On Arch greetd is enabled by phase 4,
  after `install-greeter.sh` put the greeter in `/etc/greetd`. Here it is
  part of the system from the first boot, so it starts only once
  `/etc/greetd/hyprland.lua` exists (phase 4); until then a text console
  logs in.
- **greetd's command.** `config.toml` is read from the dotfiles; its
  `Hyprland` gets a store path, as greetd's own PATH has no system programs.
  The greeter's session gets its PATH from pam_env.
- **Root's copy of the login screen's installer.** `install-system.sh`
  copies `install-greeter.sh` and what it installs as root to
  `/usr/local/lib/jupiter/greeter`, where the Settings app's Lock Screen tab
  runs it through pkexec. Here that path is a link (tmpfiles) to a store
  copy, with bash by store path and its tools on PATH, since pkexec's PATH
  has no NixOS profile. The dotfiles' `install-greeter.sh` leaves a PAM
  stack that is a link alone (NixOS's are), so it never writes Arch's
  stacks over NixOS's.
- **The lock screen's finger.** The dotfiles' `pam/fingerprint.conf` names
  `pam_fprintd.so`, which NixOS's PAM cannot find by name. `login.nix`
  declares the same stack with the store path as
  `/etc/pam.d/jupiter-fingerprint`, and the dotfiles' `LockService` runs
  that one where it exists (only root writes `/etc/pam.d`), and their own
  everywhere else.
- **zsh's plugins.** `.zshrc` sources each from the first folder of
  `XDG_DATA_DIRS` (then `/usr/share`) that has it, as `zsh/plugins/<name>/`
  (Arch's layout) or `<name>/`; NixOS's profile, on `XDG_DATA_DIRS`, has
  them once `login.nix` links zsh-syntax-highlighting's folder into it.
- **Arch paths fixed in the dotfiles.** Linked under `/usr/share` by
  tmpfiles: `wayland-sessions` and `xsessions` (the login screen's session
  list, where NixOS keeps uwsm's Hyprland session), `X11/xkb` (the keyboard
  page's `FileView`), `themes` (adw-gtk3, which the GTK colours' CSS
  imports by URL), and for working on the repos `Kvantum`
  (`kvantum-template.py`'s default) and `hypr` (`.luarc.json`'s stubs).
- **The XDG menu.** The dotfiles set `XDG_MENU_PREFIX=arch-` for
  archlinux-xdg-menu; `desktop.nix` writes an `arch-applications.menu` of
  every app.
- **uwsm's desktop entries.** Arch's pacman hook writes cleaned copies of
  the entries uwsm refuses (Nextcloud's) to `/usr/local/share`; here
  `desktop-entries.py` runs the dotfiles' own cleaner over the system
  profile's applications as it is built.
- **User units' drop-ins.** `ConditionUser=!greeter` on the same units
  `install-system.sh` lists, as NixOS drop-ins (`asDropin`).
- **hyprpolkitagent** ships its unit in `share/systemd/user`, where NixOS
  does not look: moved to `lib/` and wanted by `graphical-session.target`.
- **gnome-keyring and `login`.** NixOS adds pam_gnome_keyring to `login`
  when gnome-keyring is on; the lock screen checks the password through
  `login`, and on an encrypted disk that would encrypt the plain login
  keyring with it. `login.nix` turns it off, as Arch has it.
- **Fingerprints.** NixOS's fprintd puts pam_fprintd in every stack by
  default (and `sufficient`, so the lock screen's password would wait on the
  reader). `enablePam` is off, and only sudo and polkit get it, with the
  Arch phase 4's `max-tries=3 timeout=10`. Without a reader pam_fprintd
  returns at once, so no reader check is needed.
- **Firewall.** NixOS's is on; Arch's ufw is installed but off. KDE
  Connect's ports are opened to the private ranges only, where
  `programs.kdeconnect` would open them to every network. It stays on
  iptables, NixOS's default: Docker writes iptables rules of its own, which
  nftables' NixOS module says do not work beside it without intervention.
- **Updates come with the repo.** `flake.lock` names the exact revision of
  each input (nixpkgs' nixos-unstable, lanzaboote's release, home-manager's
  and Stylix's default branches, the dotfiles' root files and theme
  schemes), so every machine and CI build the same system. A machine
  moves when its copy pulls a newer lock: `bootstrap.sh 2` pulls, then
  rebuilds. `.github/workflows/update-flake-lock.yml` updates the lock
  weekly (or on demand), runs CI's NixOS checks on it, and only then
  commits it. A fork updates its own the same way, or with `nix flake
  update` and a commit.
- **Bounded growth.** Ten boot entries (lanzaboote's limit follows
  systemd-boot's), generations older than a month collected weekly, the
  store deduplicated: each generation's kernel and initrd would otherwise
  fill the 1 GiB ESP.
- **Qt's plugins.** `qt.enable` sets `QT_PLUGIN_PATH`, without which
  Quickshell finds no .webp support and Qt apps neither qt6ct nor Kvantum;
  the theme stays the dotfiles' (`QT_QPA_PLATFORMTHEME` in `uwsm/env`).
- **The TPM's crypttab options** are declared, not edited: phase 4 writes
  `tpm` and `volumeKey` into the machine's settings and rebuilds, and
  `base.nix` adds `tpm2-device=auto` and `fixate-volume-key=` to the
  initrd's crypttab line. The root is always named `/dev/mapper/root`, so
  the Arch installer's step that changed `root=UUID=` is not needed.
- **Secure Boot** is lanzaboote's: phase 1 makes the keys with sbctl into
  `/mnt/var/lib/sbctl` before `nixos-install` (lanzaboote signs during it)
  and enrols them, Microsoft's and the firmware's own beside them, in Setup
  Mode. Every generation boots through a signed stub holding its command
  line and the hashes of its kernel and initrd, which are kept beside it on
  the ESP; Arch's UKI holds all three whole.
- **Subvolumes:** `@nix` at `/nix` where Arch has `@pkg`.
- **No reflector, no wireless-regdom file:** the binary cache replaces
  mirrors, and the regulatory domain is a `cfg80211` option from the
  country phase 1 finds for the time zone.
- **PipeWire's JACK:** NixOS deprecates the global JACK replacement; run
  JACK apps with `pw-jack`.

## Theming

The dotfiles' wallust templates colour the shell, GTK, Qt, kitty and nvim
on NixOS exactly as on Arch: `apply.sh` renders them when a theme is
applied, with the Settings app's accent, font and glass. Those are choices
made at runtime, so the templates are not built by Nix, and the live tint,
`--shell-only` and themes made from a wallpaper work as on Arch.

`nixos/theme.nix` adds Stylix for what the templates do not reach: the
console's colours (the LUKS prompt and the text login among them),
fontconfig's default families, and btop, mpv and Zed through home-manager.
Its colours are the dotfiles' `.config/wallust/base16/<theme>.json`, the
base16 slots nvim's template fills, which their `scripts/base16-schemes.py`
renders from wallust's themes. Stylix's own GTK, Qt, kitty, nvim and
Hyprland targets stay off: they would draw over the templates, without the
glass.

- **Pre-built themes.** The user's home-manager configuration has a
  specialisation for each file in `base16/`, built with the system: ten
  add some seconds to a rebuild's evaluation and a few MB to the store. The
  configuration is linked at `/etc/jupiter/home`, and `apply.sh` runs
  `specialisation/<theme>/activate` under it once it has rendered the
  templates (well under a second), or the plain generation, the default
  theme's, for a theme without a file. At boot home-manager activates the
  plain one; the shell's `apply.sh` at login switches back.
- **What Stylix owns.** btop's and mpv's configs become links into the store,
  so their settings are declared in `theme.nix`, not saved from the apps;
  Zed keeps writing its `settings.json`, which home-manager merges into. A
  config one of them wrote before is kept as `<file>.before-stylix`. The
  packages stay `packages.nix`'s (`package = null`).
- **System-wide, one theme.** The console and fontconfig take the default
  theme (Oxocarbon-Dark, `apply.sh`'s): a specialisation of the system
  would be a boot entry, and switching it needs root.
- **Adding a theme** to pre-build: `scripts/base16-schemes.py <theme>` in the
  dotfiles, commit, and rebuild once the flake's `dotfiles` input has it.
- **Not themed:** the boot menu. lanzaboote's signed systemd-boot, which the
  TPM binding relies on, has no colours or background to set, and with
  `boot.loader.timeout = 0` it is not shown. Plymouth stays off, which keeps
  the passphrase prompt on the console.

## Package differences

| Arch | NixOS |
|---|---|
| wallust (AUR, 3.5.1 pinned in CI) | `wallust` 3.5.2 |
| brave-origin-bin (AUR) | `brave`: nixpkgs has no Brave Origin |
| onlyoffice-bin | `onlyoffice-desktopeditors` |
| claude-desktop (AUR) | none in nixpkgs: left out |
| hypr-kdeconnect-fix-git (AUR) | none: KDE Connect's remote input is missing until it is packaged |
| steam + lib32 drivers by hand | `programs.steam` (32-bit graphics included) |
| docker (installed) | `virtualisation.docker.enable` (the daemon runs) |
| ufw | NixOS's firewall, see above |
| qemu, swtpm, edk2-ovmf (the VM checks) | not yet listed: the VM rig is Arch's (below) |

## Why nixos-unstable

Checked against nixos-26.05, the stable release when this was written, with
the dotfiles of the time:

- **Hyprland 0.55.4 rejects the desktop's config**
  (`Hyprland --verify-config`): `cursor.lua` listens for an event it does
  not have (`input.keyboard.key`), `keybinds.lua`'s swipe-down gesture
  gives `action` callbacks where it takes a string only, and `tablet.lua`
  sets the tablet's `pressure_range_min/max`, which it does not know. The
  session would start with those errors, without what follows them in
  those files: the cursor's handling, the swipe down to the shell's
  dropdown and the tablet's pressure range. The greeter's config passes. Unstable's 0.57.2 passes
  both, as Arch's does: the dotfiles follow Hyprland as Arch ships it.
- **Quickshell 0.3.0**, where the dotfiles are written against 0.3.2's
  types: the dotfiles' QML suites (the shell's logic, the lock and login
  screens) pass on both, flaking now and then on either alike, so no
  difference showed; qmllint against 0.3.0's types was not run.
- **The modules** use `services.fprintd.enablePam`, which 26.05 lacks.
- uwsm 0.26 against 0.27, and the rest of the packages: nothing found.

So stable as it is would cost the desktop part of its config. Two ways to
it, if a stable base is wanted: stable with Hyprland and Quickshell from
unstable (a second nixpkgs input and an overlay; the two then bring
unstable's libraries along, a larger closure), or wait for the next
release to carry them. Rolling, as Arch is, stays the simplest match.

## Status

What works and how it is checked:

- **Evaluated:** `nixos/` with `hosts/example` evaluates to a complete
  system against nixos-unstable (Quickshell 0.3.2, Hyprland 0.57), in CI
  with the real lanzaboote and the dotfiles of the push.
- **Built and run:** `finger-asked` (an empty answer succeeds, a typed one
  fails, with no PATH), `disk-encrypted`, and root's greeter tree; in CI
  the dotfiles' Hyprland config verifies with NixOS's Hyprland, and their
  QML suites pass in NixOS's Quickshell.
- **Tested** (Jupiter-testing, `installer/test_nixos_*.py` and
  `installer/security/test_nixos_*.py`, beside Arch's): phase 1 against
  stand-in commands, phases 2 to 4, the TPM step, `desktop-entries.py`,
  detection, the settings schema, and the generated PAM stacks.
- **Not yet done** — the roadmap, roughly in order:
  1. Install in a VM end to end. Jupiter-testing's `vm/` rig boots the Arch
     ISO; it needs the NixOS ISO's kernel and console, and phase 1's answers.
     NixOS's own test driver (`nixosTest`) could cover phases 2 to 4 and
     log in at the greeter.
  2. Check on hardware that lanzaboote's stub sets `StubInfo`, which
     `jupiter/tpm.py` reads to tell that a signed image started this boot.
  3. Find the rest of what the `/usr/share` links stand in for without them:
     the greeter's sessions, the keyboard page's layouts and the GTK
     theme's import are fixed paths in Python, QML and CSS.
  4. Merge the dotfiles' branch to their `main` with this one: until then
     the lock screen's finger fails on NixOS (the password works).

## Development

As for the Arch side: `./check.sh` lints and tests this repo, both systems'
suites, and `./check.sh check all` every repo. The evaluation tests need
Nix and a nixpkgs (`JUPITER_NIXPKGS`, or Nix's `<nixpkgs>`), and are
skipped without them; nixfmt formats `*.nix`, and statix (`statix.toml`)
and deadnix lint them, where they are installed (CI has all three).

```bash
nix eval .#nixosConfigurations.example.config.system.build.toplevel.drvPath
```

## Customising

As on Arch: fork this repo and the dotfiles, change `nixos/packages.nix`,
point `flake.nix`'s `dotfiles` input and `jupiter/config.py` (or
`DOTFILES_REPO`, `DOTFILES_PUSH_URL`) at your fork, and commit your
machine's `hosts/<name>/` to it. The rest of `nixos/` merges cleanly from
upstream. The root files of the dotfiles come from `flake.lock`'s revision;
to build from your clone instead: `nixos-rebuild switch --sudo --flake
.#<host> --override-input dotfiles ~/Jupiter-dotfiles`.
