#!/usr/bin/env bash
# Fetch this installer, or update it, and run it: bootstrap.sh [phase ...]
set -euo pipefail

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
