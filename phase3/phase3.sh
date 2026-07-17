#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACMAN_LIST="$SCRIPT_DIR/pacman.txt"
AUR_LIST="$SCRIPT_DIR/AUR.txt"

# Colors
COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'

log_info()  { echo -e "${COLOR_BLUE}==>${COLOR_RESET} $*"; }
log_ok()    { echo -e "${COLOR_GREEN}==>${COLOR_RESET} $*"; }
log_warn()  { echo -e "${COLOR_YELLOW}!!${COLOR_RESET} $*"; }
log_error() { echo -e "${COLOR_RED}!!${COLOR_RESET} $*"; }

install_with_fallback() {
    local pkg="$1"
    shift
    local mgr=("$@")

    if "${mgr[@]}" -S --needed --noconfirm "$pkg" 2>/dev/null; then
        return 0
    fi

    log_warn "'$pkg' not found directly, searching..."
    mapfile -t matches < <("${mgr[@]}" -Ss "$pkg" | grep '^[a-z]' | awk '{print $1}')

    if [[ ${#matches[@]} -eq 0 ]]; then
        log_error "No matches found for '$pkg', skipping"
        return 1
    fi

    echo "Did you mean one of these?"
    select choice in "${matches[@]}" "Skip"; do
        if [[ "$choice" == "Skip" || -z "$choice" ]]; then
            log_warn "Skipping '$pkg'"
            return 1
        fi
        "${mgr[@]}" -S --needed --noconfirm "$choice"
        return 0
    done
}

install_from_list() {
    local list="$1"
    shift
    local mgr=("$@")
    [[ -f "$list" ]] || { log_warn "No $list found, skipping"; return; }

    while IFS= read -r pkg <&3; do
        pkg="$(echo "$pkg" | xargs)"
        [[ -z "$pkg" ]] && continue
        install_with_fallback "$pkg" "${mgr[@]}"
    done 3< "$list"
}

log_info "Phase 3: installing user-defined programs"

HAS_PARU=false
command -v paru &>/dev/null && HAS_PARU=true

HAS_AUR_LIST=false
[[ -f "$AUR_LIST" ]] && HAS_AUR_LIST=true

if [[ "$HAS_PARU" == false && "$HAS_AUR_LIST" == true ]]; then
    log_warn "AUR.txt found but paru is not installed."
    log_warn "Install paru (see phase 2), or skip AUR packages for this run."
    read -rp "Skip AUR.txt and continue with pacman packages only? [y/N] " reply
    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        log_error "paru is required to install AUR.txt. Aborting."
        exit 1
    fi
fi

log_info "Updating system before install"
if [[ "$HAS_PARU" == true ]]; then
    paru -Syu --noconfirm
else
    sudo pacman -Syu --noconfirm
fi

if [[ "$HAS_PARU" == true ]]; then
    install_from_list "$PACMAN_LIST" paru
    install_from_list "$AUR_LIST" paru
else
    install_from_list "$PACMAN_LIST" sudo pacman
fi

log_ok "Phase 3 complete"
