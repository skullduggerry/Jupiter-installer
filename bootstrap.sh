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

repo=${INSTALLER_REPO:-https://codeberg.org/skullduggery/Jupiter-installer.git}
dir=$HOME/$(basename "$repo" .git)

# The live ISO has Python, but not git.
command -v git >/dev/null || pacman -Sy --noconfirm git

if [[ -d $dir/.git ]]; then
    git -C "$dir" pull --ff-only
else
    git clone "$repo" "$dir"
fi
cd "$dir"
# Piped from curl, stdin is the script: read the answers from the terminal.
exec python3 -m jupiter "$@" </dev/tty
