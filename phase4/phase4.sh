#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../config.sh"

REPO_NAME="$(basename "$DOTFILES_REPO_HTTPS" .git)"
DOTFILES_DIR="$HOME/$REPO_NAME"

BACKUP_DIR="$HOME/.dotfiles-backup/$(date +%Y%m%d-%H%M%S)"

COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'

log_info()  { echo -e "${COLOR_BLUE}==>${COLOR_RESET} $*"; }
log_ok()    { echo -e "${COLOR_GREEN}==>${COLOR_RESET} $*"; }
log_warn()  { echo -e "${COLOR_YELLOW}!!${COLOR_RESET} $*"; }
log_error() { echo -e "${COLOR_RED}!!${COLOR_RESET} $*"; }

USE_SSH=false
for arg in "$@"; do
    case "$arg" in
        --ssh) USE_SSH=true ;;
        *) log_error "Unknown option: $arg"; exit 1 ;;
    esac
done

log_info "Phase 4: applying dotfiles"

if [[ -d "$DOTFILES_DIR/.git" ]]; then
    log_info "Dotfiles repo already present at $DOTFILES_DIR, pulling latest"
    git -C "$DOTFILES_DIR" pull
elif [[ -d "$DOTFILES_DIR" ]]; then
    log_error "$DOTFILES_DIR exists but is not a git repo. Move it aside and re-run."
    exit 1
else
    log_info "Cloning dotfiles repo into $DOTFILES_DIR"
    git clone "$DOTFILES_REPO_HTTPS" "$DOTFILES_DIR"
fi

if [[ "$USE_SSH" == true ]]; then
    log_info "Switching origin remote to SSH"
    git -C "$DOTFILES_DIR" remote set-url origin "$DOTFILES_REPO_SSH"
fi

link_entry() {
    local src="$1" target="$2"

    if [[ -L "$target" ]]; then
        rm "$target"
    elif [[ -e "$target" ]]; then
        log_warn "Backing up existing $target"
        mkdir -p "$(dirname "$BACKUP_DIR/${target#"$HOME"/}")"
        mv "$target" "$BACKUP_DIR/${target#"$HOME"/}"
        BACKED_UP_ANYTHING=true
    fi

    mkdir -p "$(dirname "$target")"
    ln -s "$src" "$target"
    log_info "Linked $target -> $src"
}

mkdir -p "$BACKUP_DIR"
BACKED_UP_ANYTHING=false

for entry in "$DOTFILES_DIR"/*; do
    name="$(basename "$entry")"
    [[ "$name" == ".git" ]] && continue

    if [[ "$name" == "config" ]]; then
        for sub_entry in "$entry"/*; do
            sub_name="$(basename "$sub_entry")"
            link_entry "$sub_entry" "$HOME/.config/$sub_name"
        done
    else
        link_entry "$entry" "$HOME/$name"
    fi
done

if [[ "$BACKED_UP_ANYTHING" == true ]]; then
    log_warn "Some existing files were backed up to $BACKUP_DIR"
else
    rmdir "$BACKUP_DIR" 2>/dev/null || true
fi

log_ok "Phase 4 complete"
