Installer Script Version 1.0

Installer.sh runs the subscripts, letting you decide which ones to run during your system install.
Simply clone the repository or run it using curl. 

The main concept is customization. Both the dotfiles and installer are intended to be forked from the main branch and adatped to the users needs. This could entail adding programs to the user-defined package list, configuring the dotfiles or majorly changing the setup steps. It is recommended to keep installer-dependent files unchanged to avoid merge/upstream conflicts unless you know what you are doing.

Phase 1: does the actual system installation, similar to archinstall. Does drive configuration, driver setup, user account creation etc. can be skipped in favour of manual installation or archinstall

Phase 2: Installs all components (such as hyprland or quickshell) as well as recommended programs such as neovim

Phase 3: Installs user-defined packages, such as steam. These can be defined in pacman.txt and AUR.txt

Phase 4: sets up the dotfiles. Pulls them from the main branch (Jupiter-dotfiles) by default.
