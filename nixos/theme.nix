# Stylix, in the dotfiles' theme. The dotfiles' own templates colour the
# shell, GTK, Qt, kitty and nvim as on Arch: apply.sh renders them when a
# theme is applied, with the Settings app's accent, font and glass, which no
# build can know. Stylix themes what they do not reach: the console, the
# default font families, and btop, mpv and Zed (home-manager's). Its scheme
# is one of the dotfiles' .config/wallust/base16/*.json, the slots nvim
# gets, which scripts/base16-schemes.py renders from wallust's themes.
#
# Each of those themes is a specialisation of the user's home-manager
# configuration, built with the system, so a theme switches in seconds
# without a rebuild. /etc/jupiter/home is the configuration; apply.sh runs
# specialisation/<theme>/activate under it after rendering, or the plain
# generation (the default theme's) for a theme without one. The system's
# own (the console's colours, fontconfig) stays the default theme's.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (config.jupiter) dotfiles settings;
  folder = "${dotfiles}/.config/wallust/base16";
  themes = map (lib.removeSuffix ".json") (
    lib.filter (lib.hasSuffix ".json") (lib.attrNames (builtins.readDir folder))
  );
  # apply.sh's theme until one is picked.
  default = "Oxocarbon-Dark";
  scheme = theme: lib.importJSON "${folder}/${theme}.json";
  colours = theme: {
    base16Scheme = scheme theme;
    polarity = (scheme theme).variant;
  };
  home = config.home-manager.users.${settings.user};
in
{
  assertions = [
    {
      assertion = lib.elem default themes;
      message = "The dotfiles have no ${folder}/${default}.json, the default theme's scheme: run their scripts/base16-schemes.py.";
    }
  ];

  stylix = colours default // {
    enable = true;
    # Only what is named below: the rest is the dotfiles' templates'.
    autoEnable = false;
    # The families the dotfiles' templates and the shell name.
    fonts = {
      monospace = {
        package = pkgs.nerd-fonts.jetbrains-mono;
        name = "JetBrainsMono Nerd Font";
      };
      sansSerif = {
        package = pkgs.noto-fonts;
        name = "Noto Sans";
      };
      serif = {
        package = pkgs.noto-fonts;
        name = "Noto Serif";
      };
      emoji = {
        package = pkgs.noto-fonts-color-emoji;
        name = "Noto Color Emoji";
      };
    };
    targets = {
      console.enable = true;
      fontconfig.enable = true;
    };
  };

  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    # A config btop or Zed wrote before home-manager took it is kept beside
    # it, rather than stopping the activation.
    backupFileExtension = "before-stylix";
    users.${settings.user} = {
      home.stateVersion = settings.stateVersion;
      # The packages are packages.nix's: only their configs here.
      programs.btop = {
        enable = true;
        package = null;
      };
      programs.mpv = {
        enable = true;
        package = null;
      };
      # Zed keeps writing its settings.json; home-manager merges Stylix's
      # theme and fonts into it at each activation.
      programs.zed-editor = {
        enable = true;
        package = null;
      };
      stylix.targets = {
        btop.enable = true;
        mpv.enable = true;
        zed.enable = true;
      };
      specialisation = lib.genAttrs themes (theme: {
        configuration.stylix = lib.mapAttrs (_: lib.mkForce) (colours theme);
      });
    };
  };

  # Where apply.sh finds the generation and its specialisations.
  environment.etc."jupiter/home".source = home.home.activationPackage;
}
