"""Explicit developer-only frozen-client upgrade/rollback acceptance driver."""

from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import QTimer


def start_acceptance(window, output, app):
    manager = window.updates
    if not manager or not manager.engines.trust.local_feed:
        raise ValueError("Update acceptance requires an explicit local developer feed")
    output.mkdir(parents=True, exist_ok=False)
    before = window.service.engine.version
    report = {
        "client_frozen": bool(getattr(sys, "frozen", False)),
        "client_pid": os.getpid(),
        "before": before,
        "events": [],
        "scope": "local test signing key and synthetic E2 version",
    }
    phase, deadline = "check", time.monotonic() + 240
    timer = QTimer(window)
    timer.setInterval(100)
    previous = ""

    def finish(passed):
        timer.stop()
        report["passed"] = passed
        report["state"] = manager.engines.state()
        policy = manager.engines.root / "update-policy.json"
        report["highest_sequence"] = json.loads(policy.read_bytes())["sequence"] if policy.exists() else None
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if passed else 1)

    def tick():
        nonlocal phase, previous
        if manager.status != previous:
            report["events"].append(manager.status)
            previous = manager.status
        if time.monotonic() > deadline or manager.status == "failed":
            report["message"] = manager.message
            report["failure_details"] = getattr(manager, "failure_details", None)
            finish(False)
        elif phase == "check" and manager.status == "available":
            phase = "install"
            manager.install()
        elif phase == "install" and manager.status == "updated":
            report["after_upgrade"] = window.service.engine.version
            report["same_client_pid"] = os.getpid() == report["client_pid"]
            window.grab().save(str(output / "upgraded.png"))
            phase = "rollback"
            manager.rollback()
        elif phase == "rollback" and manager.status == "rolled_back":
            report["after_rollback"] = window.service.engine.version
            window.grab().save(str(output / "rolled-back.png"))
            finish(report["after_upgrade"] != before and report["after_rollback"] == before)

    window.navigate(3)
    timer.timeout.connect(tick)
    timer.start()
    manager.check()
    window._update_acceptance_timer = timer
