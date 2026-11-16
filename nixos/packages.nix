# Your own packages: the Arch installer's phase 3 (packages/pacman.txt and
# aur.txt), declared. Fork the repo and change this list; the rest of
# nixos/ merges cleanly from upstream. Where nixpkgs has no package for one
# the Arch lists name, docs/nixos.md says so.
{ pkgs, ... }:
let
  # The private ranges, IPv6's link-local among them: the phone finds the
  # computer by broadcast and the two connect directly, so KDE Connect works
  # on any local network and is never reachable from the internet.
  local4 = "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16";
  local6 = "fe80::/10";
  kdeconnect = "1714-1764";
in
{
  environment.systemPackages = with pkgs; [
    nextcloud-client
    # KDE Connect, with what it needs outside Plasma: sshfs to browse the
    # phone's files, oxygen-sounds for the ring when the phone looks for this
    # computer. Its ports are opened below, to the local networks only.
    kdePackages.kdeconnect-kde
    sshfs
    kdePackages.oxygen-sounds
    zed-editor
    obsidian
    keepassxc
    prismlauncher
    btop
    fastfetch
    mpv
    android-tools
    onlyoffice-desktopeditors
    brave
    vesktop
    revanced-cli

    # What the checks (./check.sh in each Jupiter repo) run. Drop them if you
    # do not work on the repos.
    ruff
    mypy
    python3Packages.coverage
    shellcheck
    shfmt
    stylua
    lua-language-server
    nixfmt
    actionlint
  ];

  virtualisation.docker.enable = true;
  # Steam brings the 32-bit drivers of the graphics drivers itself (the Arch
  # installer adds lib32-* by hand).
  programs.steam.enable = true;
  # Firmware updates, Secure Boot's revocation list (dbx) among them. Running
  # them is yours: `fwupdmgr refresh && fwupdmgr update`, then `bootstrap.sh
  # 3` again if the disk asked for its passphrase at the next boot.
  services.fwupd.enable = true;

  # NixOS's firewall is on, where Arch's ufw is installed but off: KDE
  # Connect gets its ports from the local networks alone, rather than
  # programs.kdeconnect's, which opens them to every network.
  networking.nftables.enable = true;
  networking.firewall.extraInputRules = ''
    ip saddr { ${local4} } tcp dport ${kdeconnect} accept
    ip saddr { ${local4} } udp dport ${kdeconnect} accept
    ip6 saddr ${local6} tcp dport ${kdeconnect} accept
    ip6 saddr ${local6} udp dport ${kdeconnect} accept
  '';
}
