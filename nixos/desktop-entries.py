"""Clean the desktop entries uwsm refuses, in a profile as it is built.

    python3 desktop-entries.py UWSM-DESKTOP-ENTRIES.PY APPLICATIONS

The dotfiles' scripts/uwsm-desktop-entries.py says what uwsm refuses and
why (Nextcloud's CloudProviders group). On Arch its pacman hook writes
copies to /usr/local/share/applications; here login.nix runs this in the
system profile's build (environment.extraSetup), and each entry it would
change, a link into the store, is replaced by the cleaned file.
"""

import importlib.util
import sys
from pathlib import Path


def main() -> None:
    script, folder = Path(sys.argv[1]), Path(sys.argv[2])
    spec = importlib.util.spec_from_file_location("uwsm_entries", script)
    assert spec and spec.loader, script
    entries = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entries)
    for entry in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
        fixed = entries.cleaned(entry.read_text())
        if fixed is None:
            continue
        entry.unlink()  # a link into the store: the copy takes its place
        entry.write_text(
            f"{entries.MARK}{entry.name} without what uwsm refuses\n{fixed}"
        )
        print(f"cleaned {entry.name}")


if __name__ == "__main__":
    main()
