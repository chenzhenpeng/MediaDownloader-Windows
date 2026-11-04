"""Offline source UI acceptance: real widget input, filters, themes and layout captures."""

from __future__ import annotations

import argparse
import base64
import io
import json
import sqlite3
import time
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from media_downloader.contracts import Capability, MediaInfo, Preview
from media_downloader.storage import Store
from media_downloader.theme import apply_theme
from media_downloader.ui import MainWindow


def seed(store, output, real_sample=None):
    image = io.BytesIO()
    Image.new("RGB", (320, 200), "#005fb8").save(image, "JPEG")
    preview = Preview(
        "示例作品 · Windows 界面验收",
        "douyin",
        "fixture",
        "video",
        1,
        (MediaInfo("video", "mp4", 576, 1024, 92.9),),
        Capability("douyin", "抖音", ("video",)),
    ).to_dict()
    preview["thumbnails"] = [base64.b64encode(image.getvalue()).decode()]
    if real_sample:
        with sqlite3.connect(f"file:{real_sample.resolve().as_posix()}?mode=ro", uri=True) as sample:
            raw = sample.execute("SELECT preview FROM tasks WHERE state='completed' LIMIT 1").fetchone()
            if raw:
                preview = json.loads(raw[0])
    ids = {}
    for index, state in enumerate(("ready", "completed", "failed", "interrupted")):
        task_id = store.create(f"https://www.douyin.com/video/{700 + index}", str(output))
        store.update(
            task_id,
            title=preview["title"] if real_sample else f"示例作品 {index + 1} · Windows 界面验收",
            state=state,
            preview=json.dumps(preview),
            error="网络连接失败，请检查网络或代理后重试。" if state == "failed" else "",
        )
        ids[state] = task_id
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real-sample-db", type=Path)
    parser.add_argument("--showcase", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    apply_theme(app)
    store = Store(args.output / "tasks.sqlite3")
    ids = seed(store, args.output.resolve(), args.real_sample_db)
    window = MainWindow(store)
    window.show()
    QTest.qWait(80)
    assert getattr(app, "chinese_translator", None) is not None
    for field in (window.input, window.queue_pane.search, window.output, window.proxy, window.cookie):
        menu = field.createStandardContextMenu()
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        assert any("粘贴" in text for text in texts)
        assert all(
            not any(word in text for word in ("Undo", "Redo", "Paste", "Copy", "Cut", "Delete", "Select All"))
            for text in texts
        )
        if field is window.input:
            from PySide6.QtCore import QPoint

            menu.popup(window.input.mapToGlobal(QPoint(12, 12)))
            QTest.qWait(30)
            assert menu.grab().save(str(args.output / "edit-context-menu.png"))
            menu.hide()
        menu.deleteLater()
    window.cookie.setText("fixture-not-a-secret")
    window.cookie.selectAll()
    menu = window.cookie.createStandardContextMenu()
    assert all(
        not action.isEnabled()
        for action in menu.actions()
        if "复制" in action.text() or "剪切" in action.text()
    )
    menu.deleteLater()
    window.cookie.clear()
    from media_downloader.ui_components import confirm_action

    def cancel_confirmation():
        dialog = app.activeModalWidget()
        assert {button.text() for button in dialog.buttons()} == {"移除记录", "取消"}
        assert dialog.defaultButton().text() == "取消"
        assert dialog.grab().save(str(args.output / "remove-dialog.png"))
        dialog.defaultButton().click()

    QTimer.singleShot(80, cancel_confirmation)
    assert not confirm_action(window, "移除记录", "移除这条历史记录？", "移除记录", "已下载的文件会保留。")
    for _ in range(200):
        if "正在读取" not in window.support_summary.text():
            break
        QTest.qWait(100)
    from media_downloader.platforms import PLATFORMS

    assert all(spec.name in window.support_text.text() for spec in PLATFORMS.values())
    assert window.platform.count() == len(PLATFORMS)
    assert all(kind in window.support_summary.text() for kind in ("视频", "图片 / 图集", "音频"))
    window.support_details.toggle.setChecked(True)
    assert "实际文件格式" in window.support_text.text()
    window.support_search.setText("YouTube")
    assert "YouTube" in window.support_text.text() and "哔哩哔哩" not in window.support_text.text()
    window.support_search.clear()
    window.support_details.toggle.setChecked(False)
    window.navigate(1)
    assert window.queue_table.rowCount() == 1 and window.queue_pane.start.isEnabled()
    assert window.queue_pane.artwork.count() == 1
    assert "576 × 1024" in window.queue_pane.media.text()
    assert not window.queue_pane.format.isEnabled()
    QTest.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.AltModifier)
    assert window.pages.currentIndex() == 2
    window.nav_buttons[1].setFocus()
    QTest.keyClick(window.nav_buttons[1], Qt.Key.Key_Down)
    assert window.pages.currentIndex() == 2 and window.nav_buttons[2].isChecked()
    QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert window.history_pane.search.hasFocus()
    QTest.keyClicks(window.history_pane.search, "no-match")
    assert window.history_table.rowCount() == 0 and window.history_pane.empty.isVisible()
    assert not window.history_pane.toolbar.isVisible() and window.history_pane.search_bar.isVisible()
    assert window.history_pane.empty_action.text() == "清除筛选"
    assert not window.history_pane.start.isEnabled()
    window.history_pane.search.clear()
    window.history_pane.filter.setCurrentIndex(window.history_pane.filter.findData("failed"))
    assert window.history_table.rowCount() == 1
    assert "网络连接失败" in window.history_pane.message.text()
    window.history_pane.manage_connection()
    assert window.platform.currentData() == "douyin" and window.pages.currentIndex() == 3
    window.connection_expander.toggle.setChecked(False)
    window.navigate(2)
    window.history_pane.filter.setCurrentIndex(0)
    # Opening a completed task chooses actual media, even when sidecar files sort first.
    media_dir = args.output / "media-open-check"
    media_dir.mkdir()
    (media_dir / "000-readme.txt").write_text("sidecar")
    (media_dir / "video.mp4").write_bytes(b"test-only-not-played")
    completed = store.get(ids["completed"])
    store.update(completed["id"], final_dir=str(media_dir.resolve()))
    for name in ("000-readme.txt", "video.mp4"):
        store.db.execute("INSERT INTO outputs VALUES (?,?,?,?)", (completed["attempt_id"], name, 1, None))
    store.db.commit()
    window.history_pane.filter.setCurrentIndex(window.history_pane.filter.findData("completed"))
    opened = []
    original_open = QDesktopServices.openUrl
    QDesktopServices.openUrl = lambda url: opened.append(url.toLocalFile()) or True
    try:
        window.selected_action(window.history_table, "file")
    finally:
        QDesktopServices.openUrl = original_open
    assert opened and Path(opened[0]).name == "video.mp4"
    assert window.history_table.horizontalHeaderItem(3).text() == "文件大小"
    assert window.history_table.horizontalHeaderItem(4).text() == "结束时间"
    window.history_pane.toggle_title()
    assert window.history_pane.full_title.isVisible()
    window.history_pane.copy_title()
    assert QApplication.clipboard().text() == completed["title"]
    window.history_pane.toggle_title()
    window.history_pane.filter.setCurrentIndex(0)
    window.resize(1280, 780)
    window.navigate(1)
    QTest.qWait(30)
    window.queue_pane.hide_details()
    window.queue_pane.refresh()
    assert not window.queue_pane.detail_panel.isVisible()
    window.queue_pane.show_details()
    assert window.queue_pane.detail_panel.isVisible()
    window.resize(900, 780)
    QTest.qWait(30)
    QTimer.singleShot(80, lambda: app.activeModalWidget().reject())
    window.queue_pane.show_details()
    assert not window.queue_pane.in_dialog and window.queue_table.rowCount() == 1
    if args.showcase:
        for index, state in enumerate(("downloading", "parsing")):
            task_id = store.create(f"https://www.douyin.com/video/{800 + index}", str(args.output.resolve()))
            store.update(
                task_id,
                state=state,
                title="正在保存的作品（界面示例）" if index == 0 else "正在获取作品信息（界面示例）",
            )
            if index == 0:
                window.service.progress[task_id] = {
                    "kind": "bytes",
                    "percent": 36.8,
                    "completed_bytes": 197568492,
                    "total_bytes": 536870912,
                    "speed_bps": 8808038,
                    "eta_seconds": 39,
                }
        window.refresh()
        window.statusBar().showMessage("界面验收示例 · 模拟任务状态")
    captures = []
    for theme in ("light", "dark"):
        window.theme.setCurrentIndex(window.theme.findData(theme))
        for width in (900, 1280):
            window.resize(width, 780)
            for page in range(4):
                window.navigate(page)
                QTest.qWait(35)
                path = args.output / f"{theme}-{width}-page{page}.png"
                assert window.grab().save(str(path))
                captures.append(path.name)
            assert window.navigation.width() == (64 if width == 900 else 208)
    window.navigate(3)
    area = window.pages.currentWidget()
    assert area.widgetResizable()
    # Real focus traversal must reach every interactive field, including scrolled settings.
    window.connection_expander.toggle.setChecked(True)
    window.theme.setFocus()
    seen = set()
    for _ in range(70):
        focused = app.focusWidget()
        if focused:
            seen.add(focused)
        QTest.keyClick(app.focusWidget() or window, Qt.Key.Key_Tab)
    assert all(
        widget in seen
        for widget in (window.theme, window.workers, window.platform, window.proxy, window.cookie)
    )
    assert not window.queue_pane.format.isVisible()
    # Inject contrast colors into the application only; never alter Windows settings.
    import media_downloader.theme as theme_module

    native_appearance = theme_module.system_appearance
    theme_module.system_appearance = lambda: (
        False,
        True,
        ("#000000", "#ffffff", "#ffff00", "#000000", "#c0c0c0"),
    )
    window.theme_manager.refresh()
    assert app.palette().window().color().name() == "#000000"
    window.navigate(1)
    assert window.grab().save(str(args.output / "contrast.png"))
    theme_module.system_appearance = native_appearance
    window.theme_manager.refresh()
    window.close()
    app.processEvents()
    store.close()
    (args.output / "report.json").write_text(
        json.dumps(
            {
                "scope": "source UI, offline synthetic fixtures; no platform claims",
                "keyboard_filters_actions": "passed",
                "themes": ["light", "dark", "injected contrast colors"],
                "widths": [900, 1280],
                "device_pixel_ratio": window.devicePixelRatioF(),
                "captures": captures,
                "time": time.time(),
                "synthetic_task_states": args.showcase,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("M3 UI acceptance passed")


if __name__ == "__main__":
    main()
