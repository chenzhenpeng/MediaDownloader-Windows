from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows Media Downloader")
    parser.add_argument("--smoke-test", type=Path, help="Save an offscreen window capture and exit")
    parser.add_argument("--smoke-page", type=int, choices=range(4), default=0)
    parser.add_argument("--smoke-width", type=int, choices=[900, 1120, 1280], default=1120)
    parser.add_argument("--update-config", type=Path, help="Explicit developer update trust configuration")
    parser.add_argument("--update-smoke-test", type=Path, help="Explicit local-feed update acceptance output")
    parser.add_argument(
        "--engine-dir", type=Path, help="Explicit local engine directory for development validation"
    )
    args = parser.parse_args()
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
    from PySide6.QtCore import QLockFile, QProcess, QTimer
    from PySide6.QtWidgets import QApplication

    from . import PROTOCOL
    from .component_store import ComponentStore as EngineStore
    from .engine import resolve_engine
    from .storage import Store, data_directory
    from .ui import MainWindow, apply_theme
    from .update_contracts import Trust, UpdateError, load_trust
    from .update_manager import default_trust_file

    app = QApplication(sys.argv[:1])
    from .localization import install_chinese

    install_chinese(app)
    app.setApplicationName("Media Downloader")
    app.setOrganizationName("MediaDownloader")
    instance_lock = QLockFile(str(data_directory() / "application.lock"))
    if not instance_lock.tryLock(0):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(None, "Media Downloader", "应用已在运行，请切换到已打开的窗口。")
        return 0
    apply_theme(app)
    store = Store(data_directory() / "tasks.sqlite3")
    try:
        bundled = resolve_engine(args.engine_dir)
        config_error = ""
        try:
            trust = load_trust(
                args.update_config or default_trust_file(), allow_local=args.update_config is not None
            )
        except UpdateError as exc:
            trust, config_error = Trust("stable", {}), exc.message
        engines = EngineStore(data_directory(), trust, bundled)
        engines.recovery_message = config_error
        engine = engines.recover()
    except (OSError, ValueError, KeyError, UpdateError):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, "内核不可用", "无法读取兼容的本地内核，请检查安装目录。")
        store.close()
        return 1
    window = MainWindow(store, engine=engine, engine_store=engines)
    if args.smoke_test:
        window.resize(args.smoke_width, 780)
        window.navigate(args.smoke_page)
    window.show()
    if args.update_smoke_test:
        from .update_acceptance import start_acceptance

        if not args.update_config or not trust.local_feed:
            parser.error("--update-smoke-test requires --update-config with a local developer feed")
        start_acceptance(window, args.update_smoke_test, app)
    if args.smoke_test:

        def capture():
            import json

            # Capture settled content rather than the transient capability-loading label.
            if "正在读取" in window.support_summary.text():
                QTimer.singleShot(100, capture)
                return
            probe = QProcess()
            active_engine = window.service.engine
            probe.start(active_engine.program, [*active_engine.arguments, "--describe"])
            if not probe.waitForFinished(20000) or probe.exitCode() != 0:
                probe.kill()
                probe.waitForFinished(1000)
                app.exit(1)
                return
            actual = json.loads(bytes(probe.readAllStandardOutput()))
            if actual["engine_version"] != active_engine.version or actual["protocol"] != PROTOCOL:
                app.exit(1)
                return
            args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_test.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "ui_frozen": bool(getattr(sys, "frozen", False)),
                        "chinese_translation_loaded": getattr(app, "chinese_translator", None) is not None,
                        "engine": actual,
                        "supported_content": window.support_summary.text(),
                        "supported_details": window.support_text.text(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if not window.grab().save(str(args.smoke_test)):
                app.exit(1)
                return
            window.close()
            app.quit()

        QTimer.singleShot(250, capture)
    try:
        return app.exec()
    finally:
        store.close()
