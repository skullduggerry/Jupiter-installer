#!/usr/bin/env bash
# The installer's checks: formatting, linters and the tests.
#
#     scripts/check.sh            check everything, non-zero exit on failure
#     scripts/check.sh --fix      format, and apply the linters' safe fixes, first
#     scripts/check.sh --staged   only the files git has staged (pre-commit)
#
# ruff formats and lints the Python and mypy checks its types (strict), shfmt
# and shellcheck the shell, set up in pyproject.toml and .editorconfig. The
# tests (python3 -m unittest) run under coverage, held to pyproject.toml's
# fail_under.
set -uo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || exit 2
cd "$repo" || exit 2

fix=0
staged=0
for arg in "$@"; do
    case $arg in
        --fix) fix=1 ;;
        --staged) staged=1 ;;
        *)
            echo "unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

# Each tool, and the package it comes in.
declare -A packages=(
    ["ruff"]=ruff ["mypy"]=mypy ["coverage"]=python-coverage
    ["shellcheck"]=shellcheck ["shfmt"]=shfmt
)
missing=()
for tool in "${!packages[@]}"; do
    command -v "$tool" >/dev/null || missing+=("${packages[$tool]}")
done
if ((${#missing[@]})); then
    echo "Some tools are missing. Install them with:" >&2
    echo "    sudo pacman -S --needed $(printf '%s\n' "${missing[@]}" | sort -u | xargs)" >&2
    exit 2
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

failures=0
fail() {
    echo "  FAIL  $*"
    failures=$((failures + 1))
}
ok() { echo "  ok    $*"; }
section() {
    echo
    echo "== $1"
    section_start=$failures
}
# Says ok if the section failed nothing.
passed() { ((failures == section_start)) && ok "$@"; }
# Fails with a tool's output, its first lines.
failed() {
    fail "$1"
    head -40 "$tmp/out" | sed 's/^/        /'
}

# The files matching git pathspecs, new ones included, or with --staged the
# staged ones.
files() {
    if ((staged)); then
        git diff --cached --name-only --diff-filter=ACMR -- "$@"
    else
        git ls-files --cached --others --exclude-standard -- "$@"
    fi | while read -r f; do
        [[ -f $f && ! -L $f ]] && printf '%s\n' "$f"
    done
}
mapfile -t python < <(files '*.py')
mapfile -t shell < <(files '*.sh' '.githooks/*')

# With --staged, a file is only fixed and staged again when it has no unstaged
# changes, which `git add` would stage along with the fix.
fixable() { ((fix)) && { ((! staged)) || git diff --quiet -- "$1"; }; }
fixed() {
    echo "  fixed $1"
    ((staged)) && git add -- "$1"
}

# A file as its formatter would write it.
# shellcheck disable=SC2094 # its name only tells ruff which settings apply
formatted() {
    case $1 in
        *.py) ruff format --quiet --stdin-filename "$1" - <"$1" ;;
        *) shfmt "$1" ;;
    esac
}

section "formatting (ruff, shfmt)"
for f in "${python[@]}" "${shell[@]}"; do
    if ! out=$(formatted "$f" 2>"$tmp/out"); then
        failed "$f does not parse"
    elif [[ $out != "$(<"$f")" ]]; then
        if fixable "$f"; then
            printf '%s\n' "$out" >"$f" && fixed "$f"
        elif ((fix)); then
            fail "$f is not formatted and has unstaged changes: format it, then stage it"
        else
            fail "$f is not formatted (run scripts/check.sh --fix)"
        fi
    fi
done
passed "$((${#python[@]} + ${#shell[@]})) files"

section "whitespace (.editorconfig)"
# Trailing whitespace, except in Markdown, where two spaces end a line.
trailing() { [[ $1 != *.md ]] && grep -qP '[ \t]+$' "$1"; }
unended() { [[ -n $(tail -c1 "$1") ]]; }
while read -r f; do
    grep -Iq . "$f" || continue # binary
    if fixable "$f" && { trailing "$f" || unended "$f"; }; then
        trailing "$f" && sed -i 's/[ \t]*$//' "$f"
        unended "$f" && printf '\n' >>"$f"
        fixed "$f"
    fi
    trailing "$f" && fail "$f has trailing whitespace"
    unended "$f" && fail "$f has no final newline"
done < <(files .)
passed "trailing whitespace, final newline"

section "python (ruff, mypy)"
if ((${#python[@]})); then
    if ((fix)); then
        for f in "${python[@]}"; do
            fixable "$f" || continue
            before=$(<"$f")
            ruff check --fix --quiet "$f" >/dev/null
            [[ $(<"$f") != "$before" ]] && fixed "$f"
        done
    fi
    ruff check --quiet --output-format concise "${python[@]}" >"$tmp/out" 2>&1 || failed "ruff"
    mypy --no-error-summary "${python[@]}" >"$tmp/out" 2>&1 || failed "mypy"
fi
passed "${#python[@]} files"

section "shell (shellcheck)"
if ((${#shell[@]})); then
    shellcheck --format=gcc "${shell[@]}" >"$tmp/out" 2>&1 || failed "shellcheck"
fi
passed "${#shell[@]} files"

section "tests (python3 -m unittest, with coverage)"
# Every Python process the tests start measures itself (coverage's .pth file
# reads COVERAGE_PROCESS_START), the phases they run as `python3 -m jupiter`
# included.
export COVERAGE_FILE=$tmp/coverage/data
mkdir "$tmp/coverage"
if COVERAGE_PROCESS_START=$repo/pyproject.toml python3 -m unittest >"$tmp/out" 2>&1; then
    passed "$(grep -m1 '^Ran ' "$tmp/out")"
else
    tail -40 "$tmp/out" >"$tmp/tail" && mv "$tmp/tail" "$tmp/out"
    failed "unittest"
fi
coverage combine --quiet --rcfile=pyproject.toml "$tmp/coverage" 2>/dev/null
if coverage report --rcfile=pyproject.toml >"$tmp/out" 2>&1; then
    ok "lines covered: $(grep '^TOTAL' "$tmp/out" | awk '{print $4}')"
else
    failed "line coverage under pyproject.toml's fail_under"
fi

echo
if ((failures)); then
    echo "FAILED: $failures problem(s)"
    exit 1
fi
echo "all checks passed"
