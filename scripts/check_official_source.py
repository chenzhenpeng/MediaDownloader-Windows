"""Read-only upstream monitoring. Clients download wheels directly from PyPI."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader.official_packages import check_latest  # noqa: E402


def main():
    wheel = check_latest()
    target = ROOT / "review/official-source.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": "official-pypi", **asdict(wheel)}, indent=2), encoding="utf-8")
    print(f"Official ParseHub {wheel.version}; clients consume the original wheel directly.")


if __name__ == "__main__":
    main()
