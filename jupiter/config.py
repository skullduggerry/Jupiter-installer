"""Where the dotfiles come from: point these at your fork (and, for NixOS,
flake.nix's `dotfiles` input, from which the system takes their root files).

Either value can also be set in the environment. Phase 4 clones over
HTTPS, which needs no keys, and pushes over SSH.
"""

import os

DOTFILES_REPO = os.environ.get(
    "DOTFILES_REPO", "https://github.com/skullduggerry/Jupiter-dotfiles.git"
)
DOTFILES_PUSH_URL = os.environ.get(
    "DOTFILES_PUSH_URL", "git@github.com:skullduggerry/Jupiter-dotfiles.git"
)
