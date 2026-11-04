"""Test-only versioned pool fixture; never included in production packages."""

import runpy
import sys
from pathlib import Path

from media_downloader import worker

version = sys.argv.pop(1)
if version == "broken":
    raise SystemExit(3)
worker.ENGINE_VERSION = version
runpy.run_path(str(Path(__file__).with_name("fixture_engine.py")), run_name="__main__")
