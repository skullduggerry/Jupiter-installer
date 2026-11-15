#!/usr/bin/env bash
# Fetch this installer, or update it, and run it: bootstrap.sh [phase ...]
# From a clone, `bootstrap.sh check|lint|test [repo ...]` checks the repos,
# as ./check.sh does (./check.sh --help).
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

# The live ISO has Python, but not git.
command -v git >/dev/null || pacman -Sy --noconfirm git

if [[ -d $dir/.git ]]; then
    # Offline, or a clone with commits its origin lacks: it runs as it is.
    git -C "$dir" pull --ff-only ||
        echo "bootstrap.sh: could not update $dir: running it as it is" >&2
elif [[ ! -f $dir/jupiter/__main__.py ]]; then
    git clone "$repo" "$dir"
fi
cd "$dir"
# Piped from curl, stdin is the script: read the answers from the terminal.
exec python3 -m jupiter "$@" </dev/tty
