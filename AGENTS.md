# Jupiter-installer: agent guide

Installs Arch Linux or NixOS with Hyprland, Quickshell and Jupiter-dotfiles, in four phases written in Python with nothing beyond its standard library. It runs as root from a live ISO and erases disks: a mistake here costs someone their data or a machine that does not boot. [README.md](README.md) says what each phase does for a user; [docs/nixos.md](docs/nixos.md) how the NixOS side maps onto Arch's.

## Git

Commit and push straight to `main`, here and in Jupiter-dotfiles and Jupiter-testing: no branches or pull requests unless asked. CI (`.github/workflows/check.yml`, the same file in all three) checks every push on Arch and on NixOS.

## Sources of truth, in order

1. This repo: the docstring of every module you change (each says what its phase does and why), then this guide.
2. The Arch Installation guide and ArchWiki for Arch; for NixOS the NixOS manual, the option documentation of the nixpkgs the flake follows (`man configuration.nix`, search.nixos.org for unstable), and lanzaboote's README.
3. The manual pages of what a phase runs: cryptsetup, systemd-cryptenroll, sbctl, bootctl, nixos-install, nixos-rebuild.

## Map

Three parts: what both systems run, what only Arch runs, what only NixOS runs. A path is in exactly one.

**Shared**

| Path | What |
| --- | --- |
| `bootstrap.sh`, `check.sh` | `curl … \| bash` entry: fetches or updates this repo, brings git and Python where either ISO lacks them, runs `python3 -m jupiter`; also forwards `check`, `lint`, `test` to `check.sh` |
| `jupiter/__main__.py` | which phases run, by system (`distro.py`) and by whether this is the live ISO |
| `jupiter/distro.py` | Arch or NixOS, ISO or installed, from `/etc/os-release` and archiso's mark; anything else is refused |
| `jupiter/common.py` | what every phase uses: `run`, `succeeds`, `output`, `log`, `warn` |
| `jupiter/questions.py`, `disks.py` | phase 1's questions, and its disks: the system's disk, LUKS2, data disks |
| `jupiter/dotfiles.py` | phase 4's start: the clone, its links, the first theme |
| `jupiter/secureboot.py`, `tpm.py`, `keyring.py` | Secure Boot keys, the TPM binding (phase 4's last step), the login keyring |
| `jupiter/config.py` | where the dotfiles come from (fork here) |
| `docs/` | for people: NixOS, and encrypting an existing install |

**Arch**

| Path | What |
| --- | --- |
| `jupiter/arch/phase1.py` … `phase4.py` | the phases: pacstrap and the boot from the ISO, the desktop, your packages (paru for the AUR), the dotfiles' root files |
| `jupiter/arch/common.py` | the package lists, and installing them so a broken one is skipped (`install`, `skip`) |
| `arch/packages/*.txt` | the lists: `core.txt` (phase 2), `pacman.txt`, `aur.txt` (phase 3) |

**NixOS**

| Path | What |
| --- | --- |
| `jupiter/nixos/` | the phases: `phase1.py` (then `hosts/<name>/` and `nixos-install`), `system.py` (phases 2 and 3: one `nixos-rebuild switch`), `phase4.py` (what the flake cannot declare), `tpm.py`, `common.py` (a host's `settings.json`) |
| `flake.nix`, `flake.lock`, `nixos/` | the system: `default.nix` declares `jupiter.settings` (the schema phase 1 writes) and imports `base`, `desktop`, `packages`, `login` (greetd and PAM), `secureboot` (lanzaboote), `theme` (Stylix and home-manager) |
| `hosts/<name>/` | one machine: `settings.json` (phase 1's answers) and `hardware-configuration.nix`; `hosts/example/` is what tests and CI evaluate |

Tests live in `../Jupiter-testing` (`installer/`, `installer/security/`); see its `AGENTS.md`.

## Code

- Python's standard library only (phase 4's keyring step uses PyGObject, which phase 2 installs). Type hints throughout, mypy strict; ruff at 79 columns.
- Commands through `common.run`/`succeeds`/`output`, as argument lists, never a shell string. A secret (passphrase, password, recovery key) goes on stdin (`run(..., data=)`), never in argv, a file the system keeps, or the output.
- On NixOS nothing secret goes into `hosts/` or `nixos/`: what the flake reads ends up in the world-readable store.
- Never touch a disk the user did not choose, and never erase one without its own yes. Phase 1's disk code is shared by both systems (`jupiter/disks.py`).
- A phase can run again: check before you change, and leave what is already right as it is. On Arch a package that fails is skipped (`arch/common.py`'s `install`/`skip`) and named at the end, not fatal.
- What both systems do is written once, in the shared modules at the top of `jupiter/`; `jupiter/arch/` and `jupiter/nixos/` hold only what differs, and neither imports the other. A change to a shared step is checked on both systems.
- Arch puts system files in place in phase 4 as root; on NixOS the flake declares the same (`nixos/login.nix`, `desktop.nix`). A path the dotfiles name that NixOS does not have is linked there (the list is in `docs/nixos.md`).
- `jupiter.settings` in `nixos/default.nix` is the contract with phase 1: change its options and `jupiter/nixos/phase1.py` together.
- Nix: nixfmt-formatted, statix (`statix.toml`) and deadnix clean. Options by their full path, grouped by purpose. The flake follows nixos-unstable (`docs/nixos.md` says why stable breaks the desktop).
- Comments and docstrings say why, as the existing ones do. User-facing messages say what happened and what to do next.

## Pitfalls

- `bootstrap.sh` runs from a pipe: its answers come from `/dev/tty`, not stdin.
- A flake in a git repo sees tracked files only: phase 1 `git add`s `hosts/<name>/`; anything new the flake reads must be tracked too.
- `flake.lock` is what a machine builds: change an input in `flake.nix` and commit the lock `nix flake lock` writes with it. `.github/workflows/update-flake-lock.yml` moves it weekly, after CI's NixOS checks pass on the new one.
- On NixOS, phases 2 to 4 refuse root (nixos-rebuild builds as the user and asks sudo for the switch); on Arch, 3 and 4 do.
- `distro.OS_RELEASE` reads `JUPITER_OS_RELEASE` when set: the tests' way to run either system's phases anywhere.

## Done means

- `./check.sh` passes (`--fix` formats first): lint, then both systems' suites at a 95 % coverage floor. NixOS evaluation tests need Nix and `JUPITER_NIXPKGS` locally; CI always runs them.
- New behaviour has its test in `../Jupiter-testing/installer/`, on both systems where it applies, and a security test where it touches disks, secrets, users or what runs as root.
- Report what changed, why, how it was verified, and what was not (real hardware, a full install) and still needs to be.
