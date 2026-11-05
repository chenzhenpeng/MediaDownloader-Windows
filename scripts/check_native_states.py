"""Verify rendered parsing states in light/dark and narrow/wide WinUI windows."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "review/native/states-preview12" / str(time.time_ns())
    directory.mkdir(parents=True)
    data = ROOT / ".local/native" / f"states-{time.time_ns()}"
    reports = []
    for mode in ("narrow", "wide"):
        for theme in ("light", "dark"):
            for state in ("parsing", "ready", "failed", "download-transition"):
                report = directory / f"{mode}-{theme}-{state}.json"
                command = [
                    str(ROOT / "dist/native/MediaDownloader/MediaDownloader.exe"),
                    "--data-dir",
                    str(data),
                    "--smoke-report",
                    str(report),
                    "--smoke-page",
                    "home",
                    "--smoke-width",
                    "900",
                    "--smoke-theme",
                    theme,
                    "--smoke-parse-state",
                    state,
                ]
                if mode == "wide":
                    command += ["--smoke-maximized", "true"]
                subprocess.run(command, timeout=60, check=True)
                value = json.loads(report.read_text(encoding="utf-8"))
                assert value["backend"]["client_version"] == "0.2.0.dev12"
                assert all(value["layout"]["checks"].values())
                reports.append(
                    {
                        "mode": mode,
                        "theme": theme,
                        "fixture": state,
                        "report": str(report.relative_to(ROOT)),
                        "checks": value["layout"]["checks"],
                    }
                )
                print(f"Passed {mode}/{theme}/{state}", flush=True)
    (directory.parent / "summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
