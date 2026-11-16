# What the dotfiles install as root, declared: the Arch installer's phase 4
# runs scripts/install-system.sh and install-greeter.sh with sudo, enables
# greetd and puts pam_fprintd in sudo's and polkit's stacks. Here each comes
# from the flake's `dotfiles` input, with what NixOS lays out differently
# (no /usr/bin, PAM modules by store path, no system-local-login) changed on
# the way in; docs/nixos.md lists every change and why.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  dotfiles = config.jupiter.dotfiles;
  hyprland = config.programs.hyprland.package;

  # pam_exec's helpers, with their tools by store path: pam_exec gives no
  # PATH, and finger-asked would read a tool not found as an empty answer.
  # A tool the dotfiles add later fails the build here rather than a login.
  pamHelper =
    name: tools:
    pkgs.runCommand "jupiter-${name}" { } ''
      cp ${dotfiles}/etc/greetd/${name} $out
      chmod 0755 $out
      ${lib.concatMapStrings (tool: ''
        substituteInPlace $out --replace-fail /usr/bin/${tool.name} ${tool.package}/bin/${tool.name}
      '') tools}
      substituteInPlace $out --replace-fail '#!/bin/sh' '#!${pkgs.runtimeShell}'
      if grep -q /usr/ $out; then
        echo "${name} names a tool under /usr this module does not replace" >&2
        exit 1
      fi
    '';
  fingerAsked = pamHelper "finger-asked" [
    {
      name = "tr";
      package = pkgs.coreutils;
    }
    {
      name = "head";
      package = pkgs.coreutils;
    }
  ];
  diskEncrypted = pamHelper "disk-encrypted" [
    {
      name = "findmnt";
      package = pkgs.util-linux;
    }
    {
      name = "lsblk";
      package = pkgs.util-linux;
    }
    {
      name = "grep";
      package = pkgs.gnugrep;
    }
  ];

  # The dotfiles' stacks, as Arch reads them, for NixOS: modules outside
  # Linux-PAM by store path, the helpers by theirs, and Arch's
  # system-local-login replaced by jupiter-local-login below.
  stack =
    name:
    builtins.replaceStrings
      [
        "system-local-login"
        "pam_fprintd.so"
        "pam_gnome_keyring.so"
        "/etc/greetd/finger-asked"
        "/etc/greetd/disk-encrypted"
      ]
      [
        "jupiter-local-login"
        "${config.services.fprintd.package}/lib/security/pam_fprintd.so"
        "${pkgs.gnome-keyring}/lib/security/pam_gnome_keyring.so"
        "${fingerAsked}"
        "${diskEncrypted}"
      ]
      (builtins.readFile "${dotfiles}/etc/pam.d/${name}");

  # What scripts/install-system.sh puts in /usr/local/lib/jupiter/greeter:
  # root's copy of the login screen's installer, which the Settings app's
  # Lock Screen tab runs through pkexec, so no file in a home decides what
  # runs as root. pkexec gives it a PATH without NixOS's profile, where
  # /usr/bin/env finds no bash: bash by store path, and its tools first.
  greeterTools = with pkgs; [
    bash
    coreutils
    file
    getent
    gnused
    python3
    util-linux
  ];
  greeterRoot = pkgs.runCommand "jupiter-greeter-root" { } ''
    install -D -m 0755 ${dotfiles}/scripts/install-greeter.sh $out/scripts/install-greeter.sh
    substituteInPlace $out/scripts/install-greeter.sh \
      --replace-fail '#!/usr/bin/env bash' '#!${pkgs.bash}/bin/bash'
    sed -i '1a export PATH=${lib.makeBinPath greeterTools}:$PATH' $out/scripts/install-greeter.sh
    install -D -m 0644 ${dotfiles}/etc/greetd/config.toml $out/etc/greetd/config.toml
    install -D -m 0755 ${fingerAsked} $out/etc/greetd/finger-asked
    install -D -m 0755 ${diskEncrypted} $out/etc/greetd/disk-encrypted
    install -D -m 0644 -t $out/etc/pam.d ${dotfiles}/etc/pam.d/greetd*
  '';

  faillock = "${config.security.pam.package}/lib/security/pam_faillock.so";

  greetd = lib.importTOML "${dotfiles}/etc/greetd/config.toml";

  # Every user unit a login screen has no use for, which install-system.sh
  # gives etc/systemd/user/not-greeter.conf as a drop-in: the same list.
  notGreeter = [
    "hyprpolkitagent.service"
    "xdg-desktop-portal.service"
    "xdg-desktop-portal-gtk.service"
    "xdg-desktop-portal-hyprland.service"
    "xdg-document-portal.service"
    "xdg-user-dirs.service"
    "at-spi-dbus-bus.service"
    "pipewire.socket"
    "pipewire.service"
    "pipewire-pulse.socket"
    "wireplumber.service"
  ];
  unitsOf =
    suffix:
    lib.genAttrs (map (lib.removeSuffix suffix) (lib.filter (lib.hasSuffix suffix) notGreeter)) (_: {
      overrideStrategy = "asDropin";
      unitConfig.ConditionUser = "!greeter";
    });

  # Paths the dotfiles name as Arch lays them out, linked to where NixOS
  # keeps them: the login screen's session list, the keyboard page's layouts,
  # the GTK theme the colours import, Kvantum's theme and the zsh plugins.
  sessions = config.services.displayManager.sessionData.desktops;
  usrShare = {
    "wayland-sessions" = "${sessions}/share/wayland-sessions";
    "xsessions" = "${sessions}/share/xsessions";
    "X11/xkb" = "${pkgs.xkeyboard_config}/share/X11/xkb";
    "themes" = "/run/current-system/sw/share/themes";
    "Kvantum" = "${pkgs.kdePackages.qtstyleplugin-kvantum}/share/Kvantum";
    "hypr" = "${hyprland}/share/hypr";
    "zsh/plugins/zsh-autosuggestions" =
      "${pkgs.zsh-autosuggestions}/share/zsh/plugins/zsh-autosuggestions";
    "zsh/plugins/zsh-history-substring-search" =
      "${pkgs.zsh-history-substring-search}/share/zsh/plugins/zsh-history-substring-search";
    "zsh/plugins/zsh-syntax-highlighting" =
      "${pkgs.zsh-syntax-highlighting}/share/zsh-syntax-highlighting";
  };
in
{
  # For the checks, which build and run them on their own.
  system.build.jupiter = {
    inherit fingerAsked diskEncrypted greeterRoot;
  };

  services.greetd = {
    enable = true;
    # The dotfiles' config, its Hyprland by store path: greetd's own PATH
    # has none of the system's programs.
    settings = greetd // {
      default_session = greetd.default_session // {
        command = "${hyprland}/bin/${greetd.default_session.command}";
      };
    };
  };

  # The greeter's files are the user's theme, which phase 3 installs
  # (install-greeter.sh): until then greetd would restart a greeter that
  # cannot start, so it waits, and a text console (ctrl+alt+F2) logs in.
  systemd.services.greetd.unitConfig.ConditionPathExists = "/etc/greetd/hyprland.lua";

  security.pam.services = {
    greetd.text = stack "greetd";
    greetd-greeter.text = stack "greetd-greeter";
    # Arch's system-local-login, which the stacks above include: the
    # password, the account and the session (pam_systemd, pam_env's PATH),
    # with no keyring and no finger, both of which the stacks decide. Its
    # password is checked as Arch's system-auth checks it: counted by
    # pam_faillock, and never `sufficient`, which would end the including
    # stack there and skip the lines after the include (gnome-keyring's).
    jupiter-local-login = {
      startSession = true;
      setLoginUid = true;
      updateWtmp = true;
      enableGnomeKeyring = false;
      fprintAuth = false;
      rules.auth = {
        faillock-preauth = {
          order = 11600;
          control = "required";
          modulePath = faillock;
          args = [ "preauth" ];
        };
        unix.control = lib.mkForce "[success=1 default=bad]";
        faillock-authfail = {
          order = 11800;
          control = "[default=die]";
          modulePath = faillock;
          args = [ "authfail" ];
        };
        faillock-authsucc = {
          order = 11900;
          control = "required";
          modulePath = faillock;
          args = [ "authsucc" ];
        };
        deny.enable = false;
      };
    };
    # The lock screen checks the password with `login`, which on Arch never
    # reaches gnome-keyring; on an encrypted disk that would encrypt the
    # plain login keyring with it (the dotfiles' etc/pam.d/greetd says how).
    login.enableGnomeKeyring = lib.mkForce false;
    # A finger is enough for sudo and polkit, and after three failed
    # matches, 10 s without a finger or with no print enrolled, the password
    # is asked for as before: the Arch installer's phase 4 line.
    sudo.fprintAuth = true;
    polkit-1.fprintAuth = true;
    sudo.rules.auth.fprintd.args = [
      "max-tries=3"
      "timeout=10"
    ];
    polkit-1.rules.auth.fprintd.args = [
      "max-tries=3"
      "timeout=10"
    ];
  };

  # A drawing tablet's pad, readable by the user at the seat.
  services.udev.packages = [
    (pkgs.runCommand "jupiter-udev-rules" { } ''
      install -D -m 0644 -t $out/lib/udev/rules.d ${dotfiles}/etc/udev/rules.d/*.rules
    '')
  ];

  systemd.user.services = unitsOf ".service";
  systemd.user.sockets = unitsOf ".socket";

  systemd.tmpfiles.rules = [
    "d /usr/local/lib/jupiter 0755 root root -"
    "L+ /usr/local/lib/jupiter/greeter - - - - ${greeterRoot}"
  ]
  ++ lib.mapAttrsToList (path: target: "L+ /usr/share/${path} - - - - ${target}") usrShare;

  # Desktop entries uwsm refuses to start (Nextcloud's): the dotfiles'
  # uwsm-desktop-entries.py cleans them in the system's profile as it is
  # built, where Arch's pacman hook writes copies to /usr/local/share.
  environment.extraSetup = ''
    ${pkgs.python3}/bin/python3 ${./desktop-entries.py} ${dotfiles}/scripts/uwsm-desktop-entries.py $out/share/applications
  '';
}
