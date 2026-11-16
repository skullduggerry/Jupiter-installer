# The Jupiter system, from one machine's settings (hosts/<name>/settings.json,
# which phase 1 writes) and the dotfiles' root files. Each module stands for
# part of the Arch installer: base.nix for phase 1's system, desktop.nix for
# phase 2, packages.nix for phase 3, login.nix and secureboot.nix for what
# phase 4 sets up as root. docs/nixos.md maps them step by step.
{ lib, ... }:
let
  inherit (lib) mkOption types;
  dataDisk = types.submodule {
    options = {
      name = mkOption {
        type = types.strMatching "[a-z0-9][a-z0-9._-]*";
        description = "Its volume's name in /dev/mapper and its key file's.";
      };
      mount = mkOption {
        type = types.strMatching "(/[a-z0-9][a-z0-9._-]*)+";
        description = "Where it is mounted.";
      };
      luks = mkOption {
        type = types.str;
        description = "The UUID of its LUKS2 volume.";
      };
      filesystem = mkOption {
        type = types.str;
        description = "The UUID of the Btrfs inside it.";
      };
    };
  };
in
{
  imports = [
    ./base.nix
    ./desktop.nix
    ./packages.nix
    ./login.nix
    ./secureboot.nix
  ];

  options.jupiter = {
    dotfiles = mkOption {
      type = types.path;
      description = "A checkout of Jupiter-dotfiles: the flake's `dotfiles` input.";
    };
    settings = mkOption {
      description = "What phase 1 asked and found, from hosts/<name>/settings.json.";
      type = types.submodule {
        options = {
          hostname = mkOption { type = types.strMatching "[a-z0-9][a-z0-9-]{0,62}"; };
          user = mkOption { type = types.strMatching "[a-z_][a-z0-9_-]{0,31}"; };
          timezone = mkOption { type = types.str; };
          locale = mkOption { type = types.str; };
          keymap = mkOption {
            type = types.str;
            description = "The console's keymap, which the disk's passphrase is typed in.";
          };
          xkb = mkOption {
            type = types.attrsOf types.str;
            default = { };
            description = "The X layout for the keymap (layout, model, variant, options), from systemd's kbd-model-map.";
          };
          country = mkOption {
            type = types.nullOr (types.strMatching "[A-Z]{2}");
            default = null;
            description = "The country of the time zone, whose Wi-Fi rules apply.";
          };
          esp = mkOption {
            type = types.str;
            description = "The UUID of the EFI system partition, mounted at /boot.";
          };
          root = mkOption {
            type = types.submodule {
              options = {
                luks = mkOption {
                  type = types.nullOr types.str;
                  default = null;
                  description = "The UUID of the LUKS2 volume under /, opened as /dev/mapper/root; null unencrypted.";
                };
                filesystem = mkOption {
                  type = types.str;
                  description = "The UUID of the Btrfs with the subvolumes.";
                };
              };
            };
          };
          data = mkOption {
            type = types.listOf dataDisk;
            default = [ ];
            description = "Encrypted data disks, each opened by a key file in /etc/cryptsetup-keys.d.";
          };
          gpus = mkOption {
            type = types.listOf (
              types.enum [
                "intel"
                "amd"
                "nouveau"
                "nvidia"
              ]
            );
            default = [ ];
            description = "The drivers phase 1 found GPUs for.";
          };
          tpm = mkOption {
            type = types.bool;
            default = false;
            description = "Whether the root volume has a TPM slot (phase 3 enrols it), which the initrd then tries.";
          };
          volumeKey = mkOption {
            type = types.nullOr (types.strMatching "[0-9a-f]{64}");
            default = null;
            description = "The hash of the root's volume key, as measured into PCR 15 (fixate-volume-key).";
          };
          stateVersion = mkOption {
            type = types.str;
            description = "The NixOS release this machine was installed with.";
          };
        };
      };
    };
  };
}
