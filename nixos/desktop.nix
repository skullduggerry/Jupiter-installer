# The desktop the dotfiles need: the Arch installer's phase 2
# (arch/packages/core.txt and the services it enables), declared. Each group
# says why, as core.txt did; what NixOS does differently is in docs/nixos.md.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  settings = config.jupiter.settings;
  encrypted = settings.root.luks != null;
in
{
  # The session: Hyprland started by uwsm, which the login screen prefers,
  # its portal, and the shell, wallpaper, idle, night light and polkit agent.
  programs.hyprland = {
    enable = true;
    withUWSM = true;
  };
  xdg.portal.extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
  # gnome-keyring keeps the apps' secrets, and gcr-4's SSH agent the keys:
  # the dotfiles point SSH_AUTH_SOCK at it, since gnome-keyring 46 has no SSH
  # agent of its own. login.nix keeps it out of the login and lock stacks.
  services.gnome.gnome-keyring.enable = true;
  services.gnome.gcr-ssh-agent.enable = true;
  programs.dconf.enable = true;
  # hyprpolkitagent ships its unit in share/, where NixOS looks for none:
  # moved to lib/, and started with every session, as `systemctl --global
  # enable` does on Arch.
  systemd.packages = [
    (pkgs.runCommand "hyprpolkitagent-unit" { } ''
      install -D -m 0644 -t $out/lib/systemd/user \
        ${pkgs.hyprpolkitagent}/share/systemd/user/hyprpolkitagent.service
    '')
  ];
  systemd.user.services.hyprpolkitagent.wantedBy = [ "graphical-session.target" ];

  # What the shell reads and drives.
  services.pipewire = {
    enable = true;
    pulse.enable = true;
    wireplumber.enable = true;
  };
  security.rtkit.enable = true;
  hardware.bluetooth.enable = true;
  services.blueman.enable = true;
  services.upower.enable = true;
  services.power-profiles-daemon.enable = true;
  # The fingerprint reader; which PAM stacks take a finger is login.nix's.
  services.fprintd.enable = true;
  services.fprintd.enablePam = false;
  # brightnessctl's udev rule lets the user at the seat set the backlight.
  services.udev.packages = [ pkgs.brightnessctl ];

  environment.systemPackages = with pkgs; [
    quickshell
    hyprpaper
    hypridle
    hyprsunset
    hyprpolkitagent
    # nm-applet and blueman-applet stay running for Wi-Fi passwords and
    # Bluetooth pairing; pavucontrol is the Audio panel's full app.
    networkmanagerapplet
    pavucontrol
    brightnessctl
    libnotify
    # secret-tool keeps the calendar's password; qalc is the launcher's
    # calculator; qtimageformats lets the shell show .webp wallpapers
    # (found through qt.enable, below).
    libsecret
    libqalculate
    kdePackages.qtimageformats
    xdg-utils
    xdg-user-dirs
    cliphist
    wl-clipboard
    wf-recorder
    zenity
    # The dotfiles' helpers, and phase 4's keyring step, which talks to
    # gnome-keyring over D-Bus with python-gobject.
    (python3.withPackages (python: [
      python.python-dateutil
      python.pygobject3
    ]))
    lua
    # wallust renders the theme; the Arch installer builds it from the AUR.
    wallust
    # `iw reg get` shows the Wi-Fi rules in use.
    iw

    # The apps the keybinds open.
    kitty
    kdePackages.dolphin
    hyprshot

    # Qt apps on Wayland, in the shell's colours: qt6ct sets their style
    # (Kvantum), icons and fonts.
    kdePackages.qtwayland
    libsForQt5.qtwayland
    kdePackages.qt6ct
    kdePackages.qtstyleplugin-kvantum
    kdePackages.breeze-icons
    adw-gtk3

    # Terminal shell and editor (nvim's plugins come through git, its
    # language servers through mason, which unpacks with unzip).
    neovim
    git
    unzip
    zsh-autosuggestions
    zsh-history-substring-search
    zsh-syntax-highlighting
  ];

  # Qt finds plugins on QT_PLUGIN_PATH, which on NixOS nothing sets but this:
  # without it Quickshell sees only its own (no .webp wallpaper, in the
  # shell or the greeter), and Qt apps neither qt6ct nor Kvantum. The theme
  # itself stays the dotfiles' choice (QT_QPA_PLATFORMTHEME in uwsm/env).
  qt.enable = true;
  # Electron and Chromium apps (Obsidian, Vesktop, Brave, …) on Wayland
  # rather than XWayland, as the NixOS wiki's Hyprland page sets them.
  environment.sessionVariables.NIXOS_OZONE_WL = "1";

  fonts.packages = with pkgs; [
    nerd-fonts.jetbrains-mono
    noto-fonts
    noto-fonts-color-emoji
  ];

  # KDE apps (Dolphin's Open With) find the installed apps through an XDG
  # menu, which the dotfiles name `arch-` (archlinux-xdg-menu's, on Arch):
  # here one menu of every app under that name.
  environment.etc."xdg/menus/arch-applications.menu".text = ''
    <!DOCTYPE Menu PUBLIC "-//freedesktop//DTD Menu 1.0//EN"
      "http://www.freedesktop.org/standards/menu-spec/1.0/menu.dtd">
    <Menu>
      <Name>Applications</Name>
      <DefaultAppDirs/>
      <DefaultDirectoryDirs/>
      <Include><All/></Include>
    </Menu>
  '';

  # The folders xdg-user-dirs makes in a home at its first login, and points
  # apps at: Downloads, and Screenshots as the pictures folder, where hyprshot
  # saves. The others are not made, so a folder synced from elsewhere, such
  # as Nextcloud's, can take their names.
  environment.etc."xdg/user-dirs.defaults".text = ''
    # Written by Jupiter's desktop.nix: the folders a new home gets.
    DOWNLOAD=Downloads
    PICTURES=Screenshots
  '';

  # systemd's TPM units and the initrd's TPM support, which only the TPM
  # binding of an encrypted root uses: left out without one. (systemd runs
  # its measurements only where a signed image's stub started the boot,
  # which lanzaboote's alone does here.)
  systemd.tpm2.enable = encrypted;
  boot.initrd.systemd.tpm2.enable = encrypted;

  # Wi-Fi in the rules of the country the time zone is in (phase 1 finds it
  # in tzdata's zone.tab), not the world's: higher power, wider channels on
  # 5 GHz for drivers that do not set it themselves.
  hardware.wirelessRegulatoryDatabase = true;
  boot.extraModprobeConfig = lib.mkIf (settings.country != null) ''
    options cfg80211 ieee80211_regdom="${settings.country}"
  '';
}
