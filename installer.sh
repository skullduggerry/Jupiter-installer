#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'

log_info()  { echo -e "${COLOR_BLUE}==>${COLOR_RESET} $*"; }
log_ok()    { echo -e "${COLOR_GREEN}==>${COLOR_RESET} $*"; }
log_warn()  { echo -e "${COLOR_YELLOW}!!${COLOR_RESET} $*"; }
log_error() { echo -e "${COLOR_RED}!!${COLOR_RESET} $*"; }

declare -A PHASES=(
    [1]="$SCRIPT_DIR/phase1/phase1.sh"
    [2]="$SCRIPT_DIR/phase2/phase2.sh"
    [3]="$SCRIPT_DIR/phase3/phase3.sh"
    [4]="$SCRIPT_DIR/phase4/phase4.sh"
)

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Phases 1-2 run from the Arch ISO (partitioning, base install).
Phases 3-4 run after reboot, as your normal user (programs, dotfiles).

Options:
  --all             Run all phases in order
  --only 1,3,4      Run only the listed phases, in the order given
  --from 2          Run phase 2 through the last phase
  -h, --help        Show this help

With no options, prompts interactively (requires a real terminal).
EOF
}

run_phase() {
    local n="$1"
    local script="${PHASES[$n]:-}"

    if [[ -z "$script" || ! -f "$script" ]]; then
        log_error "Phase $n script not found at ${script:-<unknown>}"
        exit 1
    fi

    if [[ "$n" -le 2 && "$EUID" -ne 0 ]]; then
        log_error "Phase $n must be run as root (from the Arch ISO)."
        exit 1
    fi
    if [[ "$n" -ge 3 && "$EUID" -eq 0 ]]; then
        log_error "Phase $n must NOT be run as root (paru refuses to run as root)."
        log_error "Run this as your normal user; the script will sudo when needed."
        exit 1
    fi

    log_info "Starting phase $n ($script)"
    bash "$script"
    log_ok "Phase $n complete"
}

prompt_phase_selection() {
    if [[ ! -t 0 ]]; then
        log_warn "No interactive terminal detected (stdin is not a tty)."
        log_warn "Defaulting to --all. Use --only/--from for a specific set,"
        log_warn "or download the script first for interactive prompts."
        SELECTED_PHASES=(1 2 3 4)
        return
    fi

    echo ""
    echo "Which phases do you want to run?"
    select choice in "All phases" "Choose individually" "Cancel"; do
        case "$choice" in
            "All phases")
                SELECTED_PHASES=(1 2 3 4)
                break
                ;;
            "Choose individually")
                SELECTED_PHASES=()
                for n in 1 2 3 4; do
                    read -rp "Run phase $n? [y/N] " reply
                    [[ "$reply" =~ ^[Yy]$ ]] && SELECTED_PHASES+=("$n")
                done
                break
                ;;
            "Cancel")
                log_info "Aborted by user"
                exit 0
                ;;
            *)
                echo "Invalid choice, try again."
                ;;
        esac
    done
}

SELECTED_PHASES=()

if [[ $# -eq 0 ]]; then
    prompt_phase_selection
elif [[ "$1" == "--all" ]]; then
    SELECTED_PHASES=(1 2 3 4)
elif [[ "$1" == "--only" ]]; then
    IFS=',' read -ra SELECTED_PHASES <<< "$2"
elif [[ "$1" == "--from" ]]; then
    SELECTED_PHASES=()
    for n in $(seq "$2" 4); do
        SELECTED_PHASES+=("$n")
    done
elif [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 0
else
    log_error "Unknown option: $1"
    usage
    exit 1
fi

log_info "Running phases: ${SELECTED_PHASES[*]}"

for phase in "${SELECTED_PHASES[@]}"; do
    run_phase "$phase"
done

log_ok "All selected phases complete"

if [[ " ${SELECTED_PHASES[*]} " == *" 2 "* ]]; then
    log_info "Reboot into your new system, then re-run this installer"
    log_info "(same curl command) to continue with phases 3-4."
fi
