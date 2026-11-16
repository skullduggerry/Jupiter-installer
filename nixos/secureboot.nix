# Secure Boot with keys of the system's own, on an encrypted system: the
# Arch installer's secureboot.py and sbctl, through lanzaboote. Phase 1
# makes the keys (sbctl, in /var/lib/sbctl) before nixos-install and enrols
# them, Microsoft's beside them, where the firmware is in Setup Mode;
# lanzaboote then signs systemd-boot and each generation's kernel image,
# its command line and initrd inside it, and nothing else boots under
# Secure Boot. Phase 3 binds the disk to the TPM (tpm.py), or says what is
# still missing for it. An unencrypted system boots unsigned systemd-boot.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  encrypted = config.jupiter.settings.root.luks != null;
in
lib.mkIf encrypted {
  boot.lanzaboote = {
    enable = true;
    pkiBundle = "/var/lib/sbctl";
  };
  environment.systemPackages = [ pkgs.sbctl ];
}
