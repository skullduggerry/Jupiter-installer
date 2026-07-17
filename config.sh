#!/usr/bin/env bash

: "${INSTALLER_REPO:=https://codeberg.org/skullduggery/Jupiter-installer.git}"
: "${DOTFILES_REPO_HTTPS:=https://codeberg.org/skullduggery/Jupiter-dotfiles.git}"
: "${DOTFILES_REPO_SSH:=git@codeberg.org:skullduggery/Jupiter-dotfiles.git}"

export INSTALLER_REPO DOTFILES_REPO_HTTPS DOTFILES_REPO_SSH
