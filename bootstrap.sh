#!/usr/bin/env bash
set -euo pipefail

: "${INSTALLER_REPO:=https://codeberg.org/skullduggery/Jupiter-installer.git}"

REPO_NAME="$(basename "$INSTALLER_REPO" .git)"
INSTALLER_DIR="$HOME/$REPO_NAME"

if [[ -d "$INSTALLER_DIR/.git" ]]; then
    git -C "$INSTALLER_DIR" pull
else
    git clone "$INSTALLER_REPO" "$INSTALLER_DIR"
fi

cd "$INSTALLER_DIR"
exec ./installer.sh "$@"
