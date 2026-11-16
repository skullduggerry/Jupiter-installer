# The base system: what the Arch installer's phase 1 sets up with pacstrap,
# arch-chroot and mkinitcpio, declared. Phase 1 here partitions, encrypts and
# formats as the Arch one does and writes settings.json; this turns those
# answers into the boot, the file systems, the user and the drivers.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  settings = config.jupiter.settings;
  encrypted = settings.root.luks != null;
  # The Btrfs subvolumes phase 1 makes, as the Arch one does, with @nix where
  # Arch keeps pacman's cache (@pkg): the store is what grows here.
  subvolume = name: {
    device = if encrypted then "/dev/mapper/root" else "/dev/disk/by-uuid/${settings.root.filesystem}";
    fsType = "btrfs";
    options = [
      "subvol=${name}"
      "compress=zstd"
    ];
  };
  # A missing data disk is waited for 10 s, not systemd's 90, and never holds
  # up the boot: data disks are internal, there or not.
  wait = "nofail,x-systemd.device-timeout=10s";
  gpu = name: lib.elem name settings.gpus;
  nvidiaOnly = settings.gpus == [ "nvidia" ];
in
{
  system.stateVersion = settings.stateVersion;
  nixpkgs.config.allowUnfree = true;
  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  # The initrd is systemd's, as Arch's systemd and sd-encrypt hooks make it:
  # it opens the root from crypttab's line and asks for the passphrase in the
  # console's keymap. The firmware's Linux, and Intel's and AMD's microcode
  # (hardware-configuration.nix turns it on for the CPU found).
  hardware.enableRedistributableFirmware = true;
  boot.kernelParams = [
    "zswap.enabled=0"
    "quiet"
    "loglevel=3"
  ];
  boot.loader.efi.canTouchEfiVariables = true;
  # No menu to wait at: holding Space at power-on still brings it up.
  boot.loader.timeout = 0;
  # Unencrypted, systemd-boot unsigned; encrypted, lanzaboote's signed one
  # (secureboot.nix).
  boot.loader.systemd-boot.enable = !encrypted;
  boot.loader.grub.enable = false;

  # The root volume's line in the initrd's crypttab: its volume key measured
  # into PCR 15 as it opens (the TPM binding relies on it), and once phase 4
  # enrolled the TPM, the TPM tried first and the key it must have.
  boot.initrd.luks.devices = lib.mkIf encrypted {
    root = {
      device = "/dev/disk/by-uuid/${settings.root.luks}";
      allowDiscards = true;
      crypttabExtraOpts = [
        "tpm2-measure-pcr=yes"
      ]
      ++ lib.optional settings.tpm "tpm2-device=auto"
      ++ lib.optional (settings.volumeKey != null) "fixate-volume-key=${settings.volumeKey}";
    };
  };
  # By the opened volume, never by the file system's UUID, which a disk
  # without encryption could carry (the Arch installer's tpm.py says why).
  fileSystems = {
    "/" = subvolume "@";
    "/home" = subvolume "@home";
    "/var/log" = subvolume "@log";
    "/nix" = subvolume "@nix";
    "/boot" = {
      device = "/dev/disk/by-uuid/${settings.esp}";
      fsType = "vfat";
      options = [
        "fmask=0077"
        "dmask=0077"
      ];
    };
  }
  // lib.listToAttrs (
    map (disk: {
      name = disk.mount;
      value = {
        device = "/dev/disk/by-uuid/${disk.filesystem}";
        fsType = "btrfs";
        options = [
          "compress=zstd"
          "nofail"
          "x-systemd.device-timeout=10s"
        ];
      };
    }) settings.data
  );
  # Data disks open after the root, each with its key file on it, the
  # passphrase being the fallback.
  environment.etc.crypttab = lib.mkIf (settings.data != [ ]) {
    text = lib.concatMapStrings (
      disk: "${disk.name} UUID=${disk.luks} /etc/cryptsetup-keys.d/${disk.name}.key discard,${wait}\n"
    ) settings.data;
  };
  zramSwap.enable = true;

  networking.hostName = settings.hostname;
  networking.networkmanager.enable = true;
  time.timeZone = settings.timezone;
  i18n.defaultLocale = settings.locale;
  console.keyMap = settings.keymap;
  # The desktop and the login screen type in the same layout (the dotfiles'
  # vconsole.lua reads these from /etc/vconsole.conf on Arch).
  services.xserver.xkb = {
    layout = settings.xkb.layout or "us";
    model = settings.xkb.model or "pc105";
    variant = settings.xkb.variant or "";
    options = settings.xkb.options or "";
  };

  # One administrator, through wheel, with zsh, as phase 1 and 4 make them on
  # Arch. Passwords are set by phase 1 with chpasswd and never declared:
  # anything in the configuration lands in the world-readable store.
  users.mutableUsers = true;
  programs.zsh.enable = true;
  users.users.${settings.user} = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    shell = pkgs.zsh;
  };
  security.sudo.wheelNeedsPassword = true;

  # Drivers for each GPU phase 1 found: Mesa for all but NVIDIA's from
  # Turing on, which take nvidia-open.
  hardware.graphics = {
    enable = true;
    extraPackages =
      lib.optional (gpu "intel") pkgs.intel-media-driver
      ++ lib.optional (gpu "nvidia") pkgs.nvidia-vaapi-driver;
  };
  services.xserver.videoDrivers = lib.mkIf (gpu "nvidia") [ "nvidia" ];
  hardware.nvidia = lib.mkIf (gpu "nvidia") {
    open = true;
    modesetting.enable = true;
  };
  # From the Hyprland wiki's Nvidia page, for a machine whose only GPU is one;
  # uwsm reads it for Hyprland.
  environment.etc."xdg/uwsm/env-hyprland" = lib.mkIf nvidiaOnly {
    text = ''
      export LIBVA_DRIVER_NAME=nvidia
      export __GLX_VENDOR_LIBRARY_NAME=nvidia
      export NVD_BACKEND=direct
    '';
  };
}
