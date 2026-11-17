#!/usr/bin/env bash
# Fetch this installer, or update it, and run it: bootstrap.sh [phase ...]
# The same on Arch and NixOS: the installer tells which this is. From a clone,
# `bootstrap.sh check|lint|test [repo ...]` checks the repos, as ./check.sh
# does (./check.sh --help).
set -euo pipefail

# Checking works on the clones as they are, from wherever you are: no update.
case ${1-} in
    check | lint | test)
        exec "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/check.sh" "$@"
        ;;
esac

repo=${INSTALLER_REPO:-https://github.com/skullduggerry/Jupiter-installer.git}
dir=$HOME/$(basename "$repo" .git)
# Run from a clone, that clone is the installer, wherever it is and whatever
# it is called; piped from curl, there is none yet.
if [[ -n ${BASH_SOURCE[0]-} ]]; then
    self=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
    if [[ -f $self/jupiter/__main__.py ]]; then
        dir=$self
    fi
fi

# The Arch ISO has Python but not git, which pacman brings; the NixOS ISO has
# neither, and each comes from nixpkgs for its call.
if ! command -v git >/dev/null && command -v pacman >/dev/null; then
    pacman -Sy --noconfirm git
fi
from_nixpkgs() {
    nix --extra-experimental-features 'nix-command flakes' \
        shell "nixpkgs#$1" --command "$@"
}
# type -P finds programs alone: command -v would find these functions.
git() {
    if type -P git >/dev/null; then command git "$@"; else from_nixpkgs git "$@"; fi
}
python3() {
    if type -P python3 >/dev/null; then command python3 "$@"; else from_nixpkgs python3 "$@"; fi
}

if [[ -d $dir/.git ]]; then
    # Offline, or a clone with commits its origin lacks: it runs as it is.
    git -C "$dir" pull --ff-only ||
        echo "bootstrap.sh: could not update $dir: running it as it is" >&2
elif [[ ! -f $dir/jupiter/__main__.py ]]; then
    # INSTALLER_REF: a branch or tag other than the default one.
    git clone ${INSTALLER_REF:+--branch "$INSTALLER_REF"} "$repo" "$dir"
fi
cd "$dir"
# Piped from curl, stdin is the script: read the answers from the terminal.
python3 -m jupiter "$@" </dev/tty
