# Jupiter on NixOS: Hyprland, Quickshell and the Jupiter dotfiles.
#
# Every folder of hosts/ is a machine: its settings.json (what phase 1 asked)
# and hardware-configuration.nix (nixos-generate-config's). Each becomes
# nixosConfigurations.<folder>, built with nixos-install from the ISO and
# with `bootstrap.sh 2` (nixos-rebuild) after. hosts/example is the one CI
# evaluates. docs/nixos.md says what each module takes over from the Arch
# installer's phases.
{
  description = "Jupiter on NixOS: Hyprland, Quickshell and the Jupiter dotfiles";

  inputs = {
    # Unstable, as Arch is rolling: the dotfiles target Quickshell 0.3.2,
    # which 26.05 does not have (0.3.0).
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # Secure Boot: a signed systemd-boot and signed kernel images, with keys
    # of the system's own (sbctl's, in /var/lib/sbctl).
    lanzaboote = {
      url = "github:nix-community/lanzaboote";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # What the dotfiles install as root (the login screen's PAM stack and its
    # root copy, udev rules, the user units' drop-ins), from this revision.
    # The home's clone, which phase 3 links into ~/.config, is separate.
    dotfiles = {
      url = "github:skullduggerry/Jupiter-dotfiles";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      lanzaboote,
      dotfiles,
    }:
    let
      inherit (nixpkgs) lib;
      hosts = lib.attrNames (lib.filterAttrs (_: type: type == "directory") (builtins.readDir ./hosts));
      host =
        name:
        lib.nixosSystem {
          modules = [
            lanzaboote.nixosModules.lanzaboote
            self.nixosModules.default
            ./hosts/${name}/hardware-configuration.nix
            {
              jupiter.settings = lib.importJSON ./hosts/${name}/settings.json;
              jupiter.dotfiles = dotfiles;
            }
          ];
        };
    in
    {
      nixosModules.default = ./nixos;
      nixosConfigurations = lib.genAttrs hosts host;
    };
}
