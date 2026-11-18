# Secure Boot with keys of the system's own, on an encrypted system: the
# Arch installer's secureboot.py and sbctl, through lanzaboote. Phase 1
# makes the keys (sbctl, in /var/lib/sbctl) before nixos-install and enrols
# them, Microsoft's and the firmware's own beside them, where the firmware
# is in Setup Mode; lanzaboote then signs systemd-boot and a stub for each
# generation, holding its command line and the hashes of its kernel and
# initrd (kept beside it on the ESP, shared between generations), and
# nothing else boots under Secure Boot. Phase 4 binds the disk to the TPM (tpm.py), or says what is
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
