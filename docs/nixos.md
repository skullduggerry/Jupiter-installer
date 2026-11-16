# Jupiter on NixOS

How this branch (to become the repo **Jupiter-nixos**) installs the same
desktop as [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer)
does on Arch, what it takes over unchanged, what NixOS made different, and
what is still to do. Arch stays supported: Jupiter-installer keeps its
`main`, Jupiter-dotfiles serves both, and Jupiter-testing checks all of them.

## The idea

The Arch installer is imperative: four Python phases run pacman, paru,
`arch-chroot` and `sudo` in order. On NixOS the system is a function of its
configuration, so everything that phase 2, phase 3 and the root half of
phase 4 do with packages and files becomes a NixOS module in `nixos/`, and
what remains imperative stays in Python:

| | Arch (Jupiter-installer) | NixOS (this repo) |
|---|---|---|
| Disks, LUKS, Btrfs, data disks | phase 1 | phase 1, the same code |
| Base system, boot, user, drivers | phase 1 (pacstrap, mkinitcpio, sbctl) | `nixos/base.nix`, `secureboot.nix`; phase 1 runs `nixos-install` |
| Desktop packages and services | phase 2 (`packages/core.txt`) | `nixos/desktop.nix` |
| Your packages | phase 3 (`pacman.txt`, `aur.txt`) | `nixos/packages.nix` |
| Root files of the dotfiles, greetd, PAM, finger in sudo/polkit, zsh | phase 4 (`install-system.sh`, `install-greeter.sh`, `/etc/pam.d` edits, `chsh`) | `nixos/login.nix`, `base.nix` |
| Dotfiles linked into the home, theme, keyring, fingerprint enrolment, TPM | phase 4 | phase 3 (`jupiter_nixos/dotfiles.py`, `keyring.py`, `tpm.py`) |
| Updating | `bootstrap.sh 2 3 4` (pacman -Syu, paru) | `bootstrap.sh 2` (git pull, `nixos-rebuild switch`) |

The phases here are:

1. **Install**, as root from the NixOS ISO: the Arch phase 1's questions,
   disk layout and encryption, then `hosts/<hostname>/settings.json` (the
   answers and what was found), `hardware-configuration.nix`
   (`nixos-generate-config --no-filesystems`), Secure Boot keys, and
   `nixos-install --flake` from the copy of this repo it leaves in the new
   home.
2. **System**, as your user: `nixos-rebuild switch --sudo --flake
   ~/Jupiter-nixos#<host>`. Run again after any change to `nixos/` or the
   settings, and to update.
3. **Dotfiles**, as your user: the Arch phase 4 minus what is declared.

`bootstrap.sh` runs 1 on the ISO and 2 3 otherwise, as on Arch.

## Layout

```
flake.nix                 nixpkgs (unstable), lanzaboote, the dotfiles (flake = false)
nixos/default.nix         options.jupiter: the settings' schema, and the imports
nixos/base.nix            boot, initrd crypttab, file systems, zram, user, locale, GPUs
nixos/secureboot.nix      lanzaboote, on an encrypted system
nixos/desktop.nix         core.txt: Hyprland (uwsm), Quickshell, PipeWire, keyring, fonts, ...
nixos/packages.nix        pacman.txt and aur.txt; the firewall's KDE Connect rules
nixos/login.nix           greetd, its PAM stacks, root's greeter copy, udev, drop-ins, /usr/share links
nixos/desktop-entries.py  the dotfiles' uwsm-desktop-entries.py, run as the profile is built
hosts/<name>/             settings.json + hardware-configuration.nix, one per machine
jupiter_nixos/            the Python phases
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

## What NixOS made different, and how it is handled

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
  `/etc/greetd/hyprland.lua` exists (phase 3); until then a text console
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
  Connect's ports are opened to the private ranges only (nftables), where
  `programs.kdeconnect` would open them to every network.
- **The TPM's crypttab options** are declared, not edited: phase 3 writes
  `tpm` and `volumeKey` into the machine's settings and rebuilds, and
  `base.nix` adds `tpm2-device=auto` and `fixate-volume-key=` to the
  initrd's crypttab line. The root is always named `/dev/mapper/root`, so
  the Arch installer's step that changed `root=UUID=` is not needed.
- **Secure Boot** is lanzaboote's: phase 1 makes the keys with sbctl into
  `/mnt/var/lib/sbctl` before `nixos-install` (lanzaboote signs during it)
  and enrols them, Microsoft's beside them, in Setup Mode. Every generation
  is a signed image with its command line inside, as Arch's UKI is.
- **Subvolumes:** `@nix` at `/nix` where Arch has `@pkg`.
- **No reflector, no wireless-regdom file:** the binary cache replaces
  mirrors, and the regulatory domain is a `cfg80211` option from the
  country phase 1 finds for the time zone.
- **PipeWire's JACK:** NixOS deprecates the global JACK replacement; run
  JACK apps with `pw-jack`.

## Packages nixpkgs has differently, or not

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

## Why nixos-unstable, not a stable release

Checked against nixos-26.05, the stable release when this was written, with
the dotfiles of the same branch:

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

What works and how it was checked, as of this branch's first commit:

- **Evaluated:** `nixos/` with `hosts/example` evaluates to a complete
  system (`config.system.build.toplevel.drvPath`) against nixos-unstable
  (26.11pre, Quickshell 0.3.2, Hyprland 0.57), with lanzaboote's options
  stood in for (GitHub, where lanzaboote lives, was not reachable from the
  machine this was written on).
- **Built and run:** `finger-asked` (an empty answer succeeds, a typed one
  fails, with no PATH), `disk-encrypted`, and root's greeter tree.
- **Tested** (Jupiter-testing, `nixos/`): phase 1 against stand-in
  commands, phases 2 and 3, `desktop-entries.py`, the settings schema, and
  the generated PAM stacks.
- **Not yet done** — the roadmap, roughly in order:
  1. `flake.lock`: run `nix flake lock` where GitHub is reachable and commit
     it; until then `nixos-install` locks on first use.
  2. Install in a VM end to end. Jupiter-testing's `vm/` rig boots the Arch
     ISO; it needs the NixOS ISO's kernel and console, and phase 1's answers.
     NixOS's own test driver (`nixosTest`) could cover phases 2 and 3 and
     log in at the greeter.
  3. Check on hardware that lanzaboote's stub sets `StubInfo`, which
     `tpm.py` reads to tell that a signed image started this boot.
  4. Find the rest of what the `/usr/share` links stand in for without them:
     the greeter's sessions, the keyboard page's layouts and the GTK
     theme's import are fixed paths in Python, QML and CSS.
  5. Merge the dotfiles' branch to their `main` before this repo's: until
     then the lock screen's finger fails on NixOS (the password works).
  6. CI checks every push to any Jupiter repo against Arch and NixOS
     (Jupiter-testing's `.github/PROJECT_STRUCTURE.md`, "CI"). Its layout
     takes NixOS from the Jupiter-installer branch `NIXOS_BRANCH` names in
     Jupiter-testing's `scripts/ci-repos.sh` until Jupiter-nixos exists.
  7. Rename: create `skullduggerry/Jupiter-nixos` from this branch, then
     `bootstrap.sh`'s default `INSTALLER_REPO` is right, and CI finds it
     by itself.

## Developing

The three other repos sit next to this one, as on Arch: Jupiter-testing
finds this one at `../Jupiter-nixos` or `JUPITER_NIXOS`. While this is a
branch of Jupiter-installer:

```bash
git -C ~/Jupiter-installer worktree add ../Jupiter-nixos <this branch>
cd ~/Jupiter-nixos && ./check.sh          # lint and test this repo
nix eval .#nixosConfigurations.example.config.system.build.toplevel.drvPath
```

To install from the branch before the repo exists, on the ISO:

```bash
curl -fsSL https://raw.githubusercontent.com/skullduggerry/Jupiter-installer/<branch>/bootstrap.sh |
    INSTALLER_REPO=https://github.com/skullduggerry/Jupiter-installer.git INSTALLER_REF=<branch> bash
```

## Customising

As on Arch: fork this repo and the dotfiles, change `nixos/packages.nix`,
point `flake.nix`'s `dotfiles` input and `jupiter_nixos/config.py` (or
`DOTFILES_REPO`, `DOTFILES_PUSH_URL`) at your fork, and commit your
machine's `hosts/<name>/` to it. The rest of `nixos/` merges cleanly from
upstream. The root files of the dotfiles come from `flake.lock`'s revision;
to build from your clone instead: `nixos-rebuild switch --sudo --flake
.#<host> --override-input dotfiles ~/Jupiter-dotfiles`.
