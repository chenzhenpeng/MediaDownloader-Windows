"""Verify update controls and navigation notices in isolated native windows."""

import json
import subprocess
import time
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "review/native/settings-states-preview12" / str(time.time_ns())
    directory.mkdir(parents=True)
    reports = []
    for wide in (False, True):
        for theme in ("light", "dark"):
            for component, state in product(
                ("parsehub", "engine"),
                (
                    "checking",
                    "downloading",
                    "validating",
                    "waiting",
                    "available",
                    "cancelling",
                    "failed",
                    "unconfigured",
                ),
            ):
                name = f"{'wide' if wide else 'narrow'}-{theme}-{component}-{state}"
                output = directory / f"{name}.json"
                args = [
                    str(ROOT / "dist/native/MediaDownloader/MediaDownloader.exe"),
                    "--data-dir",
                    str(ROOT / ".local/native/settings-states-preview12"),
                    "--smoke-report",
                    str(output),
                    "--smoke-page",
                    "settings",
                    "--smoke-width",
                    "900",
                    "--smoke-theme",
                    theme,
                    "--smoke-update-state",
                    state,
                    "--smoke-update-component",
                    component,
                    "--smoke-notice-navigation",
                    "true",
                ]
                if wide:
                    args += ["--smoke-maximized", "true"]
                subprocess.run(args, timeout=60, check=True)
                report = json.loads(output.read_text(encoding="utf-8"))
                assert report["backend"]["client_version"] == "0.2.0.dev12"
                checks = report["layout"]["checks"]
                assert checks and all(checks.values()), (name, checks)
                reports.append({"case": name, "checks": checks})
                print(f"Passed {name}", flush=True)
    (directory.parent / "summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
