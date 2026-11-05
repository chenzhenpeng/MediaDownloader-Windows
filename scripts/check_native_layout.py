"""Check real WinUI bounds at narrow and maximized sizes using isolated data."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = ROOT / "dist/native/MediaDownloader/MediaDownloader.exe"
    directory = ROOT / "review/native/layout-preview12"
    directory.mkdir(parents=True, exist_ok=True)
    run_directory = directory / str(time.time_ns())
    run_directory.mkdir()
    data = ROOT / ".local/native" / f"layout-{time.time_ns()}"
    reports = []
    cases = [
        (mode, page, "light", False)
        for mode in ("narrow", "maximized")
        for page in ("home", "downloads", "in_progress", "completed", "failed", "settings")
    ]
    cases += [
        ("narrow", "settings", "dark", False),
        ("maximized", "settings", "dark", False),
        ("narrow", "settings", "light", True),
        ("maximized", "settings", "dark", True),
        ("compact", "home", "dark", False),
        ("compact", "downloads", "dark", False),
    ]
    for mode, page, theme, expanded in cases:
        output = run_directory / f"{mode}-{page}-{theme}{'-expanded' if expanded else ''}.json"
        args = [
            str(executable),
            "--data-dir",
            str(data),
            "--smoke-report",
            str(output),
            "--smoke-page",
            page,
            "--smoke-width",
            "900",
            "--smoke-theme",
            theme,
        ]
        if expanded:
            args += ["--smoke-settings-expanded", "true"]
            args += ["--smoke-cookie-fixture", "true"]
        if mode in {"maximized", "compact"}:
            args += ["--smoke-maximized", "true"]
        if mode == "compact":
            args += ["--smoke-nav-collapsed", "true"]
        subprocess.run(args, timeout=60, check=True)
        if not output.exists():
            raise RuntimeError(f"No successful layout report: {mode}/{page}")
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["backend"]["client_version"] == "0.2.0.dev13"
        assert report["layout"]["checks"] and all(report["layout"]["checks"].values()), report["layout"]
        reports.append(
            {
                "mode": mode,
                "page": page,
                "theme": theme,
                "expanded": expanded,
                "report": str(output.relative_to(ROOT)),
                "scale": report["scale"],
                **report["layout"],
            }
        )
        print(
            f"Passed {mode}/{page}/{theme}/{expanded}: {report['layout']['viewport_width']:.0f} DIP",
            flush=True,
        )
    assert any(r["mode"] == "maximized" and r["viewport_width"] > 1040 for r in reports)
    (directory / "summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
