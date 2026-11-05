"""Install the pinned portable compiler into the build workspace only."""

import hashlib
import json
import subprocess
from pathlib import Path

if __package__:
    from .fetch_media_tools import fetch
else:
    from fetch_media_tools import fetch

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "packaging/windows/toolchain.json").read_bytes())
    root = ROOT / ".cache/installer-tools"
    root.mkdir(parents=True, exist_ok=True)
    installer = root / "inno-pinned.exe"
    if installer.exists():
        raise ValueError("Use a clean toolchain preparation directory")
    fetch(config["download_url"], installer, config["download_sha256"])
    destination = root / "InnoSetup7"
    subprocess.run(
        [
            str(installer),
            "/CURRENTUSER",
            "/PORTABLE=1",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/DIR={destination}",
        ],
        check=True,
    )
    with (destination / "ISCC.exe").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != config["iscc_sha256"]:
            raise ValueError("Compiler does not match pinned toolchain")
    print("Pinned portable x64 installer compiler is ready")


if __name__ == "__main__":
    main()
