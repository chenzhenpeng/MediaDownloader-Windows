from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .presentation import diagnostic_report
from .service import TaskService
from .storage import Store, extract_links
from .theme import apply_theme
from .ui_components import (
    ContentIcon,
    Expander,
    InfoBar,
    LinkInput,
    NavigationButton,
    app_icon,
    confirm_action,
)
from .windows import protect, set_window_dark_mode

STATES = {
    "queued": "排队中",
    "parsing": "正在解析",
    "ready": "可下载",
    "downloading": "正在下载",
    "finalizing": "正在保存",
    "completed": "已完成",
    "failed": "失败",
    "interrupted": "已中断",
    "cancelled": "已取消",
    "cancelling": "正在取消",
}


def text_label(text, role=""):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setObjectName(role)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def button(text, slot, primary=False):
    result = QPushButton(text)
    result.setMinimumHeight(34)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(slot)
    return result


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    return frame, layout


def fluent_icon(glyph, palette, color=None):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    icon_font = QFont("Segoe Fluent Icons", 14)
    icon_font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    painter.setFont(icon_font)
    painter.setPen(color or palette.windowText().color())
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, store: Store, engine=None, engine_store=None):
        super().__init__()
        self.store = store
        self.service = TaskService(store, self, engine=engine)
        self.updates = None
        if engine_store is not None:
            from .update_manager import UpdateManager

            self.updates = UpdateManager(self.service, engine_store, self)
        self.service.changed.connect(self.refresh)
        self.setWindowTitle("Media Downloader")
        self.resize(1200, 800)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(900, 640)
        self.nav_buttons = []
        self.announced_states = {task["id"]: task["state"] for task in store.tasks()}
        central = QWidget()
        central.setObjectName("shell")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 8, 8, 0)
        root.setSpacing(0)
        navigation = self.navigation = QWidget()
        navigation.setObjectName("navigation")
        navigation.setFixedWidth(208)
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(12, 12, 12, 16)
        nav.setSpacing(4)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 4, 0, 4)
        brand_row.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(28, 28))
        mark.setFixedSize(28, 28)
        brand_row.addWidget(mark)
        self.brand = text_label("Media Downloader", "brand")
        brand_row.addWidget(self.brand, 1)
        nav.addLayout(brand_row)
        nav.addSpacing(12)
        names = self.nav_names = ["新建下载", "下载队列", "历史记录", "设置"]
        icons = self.nav_glyphs = ["\ue710", "\ue896", "\ue81c", "\ue713"]
        for index, (name, icon) in enumerate(zip(names, icons, strict=True)):
            nav_button = NavigationButton(name, icon, navigation)
            nav_button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            nav.addWidget(nav_button)
            self.nav_buttons.append(nav_button)
            if index == 2:
                nav.addStretch()
        nav.addSpacing(16)
        self.version_label = text_label("开发预览版", "caption")
        self.version_label.setToolTip(__version__)
        nav.addWidget(self.version_label)
        root.addWidget(navigation)
        self.pages = QStackedWidget()
        self.pages.setObjectName("contentSurface")
        root.addWidget(self.pages, 1)
        self.new_page()
        self.task_page("下载队列", "管理待下载作品，查看正在进行的任务。", False)
        self.task_page("历史记录", "查找已保存的作品，或重新处理未完成的任务。", True)
        self.settings_page()
        self.statusBar().showMessage("就绪")
        QShortcut(QKeySequence("Ctrl+N"), self, lambda: self.navigate(0))
        QShortcut(QKeySequence("Ctrl+Return"), self, self.inspect)
        for index in range(4):
            QShortcut(QKeySequence(f"Alt+{index + 1}"), self, lambda i=index: self.navigate(i))
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_search)
        from PySide6.QtWidgets import QApplication

        self.theme_manager = apply_theme(QApplication.instance(), store.setting("theme", "system"))
        self.theme_manager.changed.connect(self.refresh_icons)
        self.navigate(0)
        self.refresh()
        from .ui_capabilities import CapabilityReader

        self.capability_reader = CapabilityReader(self)
        self.capability_reader.changed.connect(self.update_capability_copy)
        self.service.engine_activated.connect(self.capability_reader.refresh)
        self.capability_reader.refresh(self.service.engine)

    def page(self, title, subtitle, scroll=False):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(16)
        layout.addWidget(text_label(title, "heading"))
        layout.addWidget(text_label(subtitle, "secondary"))
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(page)
            self.pages.addWidget(area)
        else:
            self.pages.addWidget(page)
        return layout

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if index == 0:
            self.input.setFocus()
        if hasattr(self, "theme_manager"):
            self.refresh_icons()

    def new_page(self):
        layout = self.page("新建下载", "粘贴作品链接，预览后保存到电脑。", scroll=True)
        layout.setSpacing(12)
        layout.parentWidget().setMaximumWidth(1080)
        layout.addSpacing(4)
        frame, box = card()
        frame.setObjectName("linkComposer")
        box.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(text_label("作品链接", "section"))
        top.addStretch()
        box.addLayout(top)
        self.input = LinkInput()
        self.input.setAccessibleName("作品链接或分享文案")
        self.input.setPlaceholderText("粘贴作品链接或分享文案，也可以拖入链接…")
        self.input.setFixedHeight(88)
        box.addWidget(self.input)
        actions = QHBoxLayout()
        paste = button("粘贴链接", self.paste)
        paste.setObjectName("subtle")
        actions.addWidget(paste)
        clear = button("清空", self.input.clear)
        clear.setObjectName("subtle")
        actions.addWidget(clear)
        actions.addStretch()
        actions.addWidget(text_label("Ctrl + Enter", "caption"))
        self.inspect_button = button("解析并预览", self.inspect, True)
        self.inspect_button.setMinimumWidth(120)
        self.inspect_button.setEnabled(False)
        actions.addWidget(self.inspect_button)
        box.addLayout(actions)
        layout.addWidget(frame)
        self.support_summary = text_label("正在读取内核支持的平台与文件类型…", "secondary")
        layout.addWidget(self.support_summary)
        self.support_details = Expander("支持的平台与文件类型")
        self.support_rows = []
        self.support_search = QLineEdit()
        self.support_search.setPlaceholderText("搜索平台，例如快手、YouTube")
        self.support_search.setAccessibleName("搜索支持的平台")
        self.support_search.textChanged.connect(self.filter_supported_platforms)
        self.support_details.content.addWidget(self.support_search)
        self.support_text = text_label("正在读取…", "secondary")
        self.support_details.body.layout().addWidget(self.support_text)
        layout.addWidget(self.support_details)
        self.feedback = InfoBar()
        layout.addWidget(self.feedback)
        frame, box = card()
        box.setContentsMargins(16, 12, 16, 12)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(ContentIcon("folder"), 0, Qt.AlignmentFlag.AlignVCenter)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        labels.addWidget(text_label("保存到", "bodyStrong"))
        self.output = QLineEdit(
            self.store.setting(
                "output_root",
                QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation),
            )
        )
        self.output.setAccessibleName("下载保存目录")
        self.output.setObjectName("directoryInput")
        labels.addWidget(self.output)
        row.addLayout(labels, 1)
        row.addWidget(button("更改…", self.choose_output), 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addSpacing(8)
        recent_header = QHBoxLayout()
        recent_header.addWidget(text_label("最近保存", "section"))
        recent_header.addStretch()
        more = button("查看全部", lambda: self.navigate(2))
        more.setObjectName("subtle")
        recent_header.addWidget(more)
        layout.addLayout(recent_header)
        self.recent_area = QVBoxLayout()
        self.recent_area.setSpacing(6)
        layout.addLayout(self.recent_area)
        self.recent_key = None
        layout.addStretch()
        self.input.textChanged.connect(self.input_changed)

    def update_capability_copy(self, rows):
        if rows is None:
            summary, details = "正在读取内核支持的平台与文件类型…", "正在读取…"
        elif not rows:
            summary, details = "暂时无法读取平台与文件类型", "请在设置中检查当前解析内核。"
        else:
            self.support_rows = rows
            types = list(dict.fromkeys(kind for _, kinds in rows for kind in kinds.split("、")))
            summary = f"支持 {len(rows)} 个平台 · " + "、".join(types)
            details = "\n".join(f"{name}：{types}" for name, types in rows)
            details += "\n\n实际文件格式与数量以作品预览为准，下载时保留当前解析格式。"
            details += "\n平台接入处于测试阶段，部分作品需要登录或代理。"
            self.support_details.toggle.setText(f"查看 {len(rows)} 个平台的文件类型")
        self.support_summary.setText(summary)
        self.support_text.setText(details)

    def filter_supported_platforms(self):
        query = self.support_search.text().strip().casefold()
        rows = [(name, kinds) for name, kinds in self.support_rows if query in name.casefold()]
        self.support_text.setText(
            ("\n".join(f"{name}：{kinds}" for name, kinds in rows) or "没有匹配的平台。")
            + "\n\n实际文件格式与数量以作品预览为准。部分作品需要登录或代理。"
        )

    def input_changed(self):
        self.inspect_button.setEnabled(bool(self.input.toPlainText().strip()))
        if self.feedback.isVisible():
            self.feedback.setText("")

    def refresh_recent(self, tasks):
        recent = [task for task in tasks if task["state"] == "completed"][:3]
        key = tuple((task["id"], task["title"], task["final_dir"]) for task in recent)
        if key == self.recent_key:
            return
        self.recent_key = key
        while self.recent_area.count():
            entry = self.recent_area.takeAt(0)
            if entry.widget():
                entry.widget().deleteLater()
        if not recent:
            frame, box = card()
            box.setContentsMargins(16, 12, 16, 12)
            box.addWidget(text_label("暂无成功下载的作品", "bodyStrong"))
            box.addWidget(text_label("下载成功的作品会显示在这里；其他任务请查看历史记录。", "secondary"))
            self.recent_area.addWidget(frame)
        else:
            from .ui_components import SettingRow

            for task in recent:
                title = self.fontMetrics().elidedText(task["title"], Qt.TextElideMode.ElideRight, 520)
                action = button("打开文件夹", lambda checked=False, t=task: self.open_task_path(t))
                recent_row = SettingRow(title, "已保存到电脑", action, "\ue8a5")
                recent_row.setObjectName("recentRow")
                recent_row.layout().setContentsMargins(20, 14, 20, 14)
                self.recent_area.addWidget(recent_row)

    def open_task_path(self, task):
        path = Path(task["final_dir"] or task["output_root"])
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(
                self, "文件夹不存在", "保存位置已被移动或删除。可以在历史记录中重新下载作品。"
            )

    def task_page(self, title, subtitle, history):
        from .ui_tasks import TaskPane

        layout = self.page(title, subtitle)
        pane = TaskPane(self, history)
        layout.addWidget(pane, 1)
        if history:
            self.history_pane, self.history_table = pane, pane.table
        else:
            self.queue_pane, self.queue_table = pane, pane.table

    def settings_page(self):
        from .ui_settings import build_settings

        layout = self.page("设置", "按你的习惯调整外观、下载和连接。", scroll=True)
        build_settings(self, layout)

    def paste(self):
        from PySide6.QtWidgets import QApplication

        self.input.setPlainText(QApplication.clipboard().text())

    def choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择保存位置", self.output.text())
        if directory:
            self.output.setText(directory)

    def inspect(self):
        if self.pages.currentIndex() != 0:
            return
        links = extract_links(self.input.toPlainText())
        if not links:
            self.feedback.setText("未找到支持的作品链接。请粘贴下方支持平台的 http/https 链接或分享文案。")
            return
        directory = self.output.text().strip()
        if not directory or not Path(directory).is_absolute():
            self.feedback.setText("请选择完整的下载目录。")
            return
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            import tempfile

            with tempfile.TemporaryFile(dir=directory):
                pass
            self.store.set_setting("output_root", directory)
            self.service.submit(links, directory)
        except OSError:
            self.feedback.setText("无法访问保存位置，请选择可写目录。")
            return
        self.navigate(1)

    def selected_action(self, table, action):
        if table.currentRow() < 0:
            self.statusBar().showMessage("请先选择一项任务。", 4000)
            return
        task_id = table.item(table.currentRow(), 0).data(Qt.ItemDataRole.UserRole)
        task = self.store.get(task_id)
        if not task:
            return
        if action == "retry":
            self.service.retry(task_id)
            self.navigate(1)
        elif action == "cancel":
            self.service.cancel(task_id)
        elif action in {"open", "file"}:
            path = Path(task["final_dir"] if task["state"] == "completed" else task["output_root"])
            if action == "file":
                if task["state"] != "completed":
                    return
                files = self.store.db.execute(
                    "SELECT relative_path FROM outputs WHERE attempt_id=? ORDER BY relative_path",
                    (task["attempt_id"],),
                ).fetchall()
                extensions = {
                    ".mp4",
                    ".mkv",
                    ".webm",
                    ".mov",
                    ".jpg",
                    ".png",
                    ".jpeg",
                    ".webp",
                    ".gif",
                    ".m4a",
                    ".mp3",
                }
                media = next(
                    (entry[0] for entry in files if Path(entry[0]).suffix.lower() in extensions), None
                )
                if media is None:
                    media = next(
                        (entry[0] for entry in files if Path(entry[0]).name in {"正文.md", "正文.txt"}), None
                    )
                path = path / media if media else path
            if not path.exists():
                QMessageBox.information(self, "文件不存在", "文件或目录已被移动或删除，可以重新下载作品。")
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.statusBar().showMessage("无法打开，请检查 Windows 默认应用设置。", 5000)
        elif action == "remove":
            if confirm_action(self, "移除记录", "移除这条历史记录？", "移除记录", "已下载的文件会保留。"):
                self.service.remove_history(task_id)
                self.statusBar().showMessage("正在移除记录，已下载的文件会保留。", 6000)

    def refresh(self):
        if not hasattr(self, "history_pane"):
            return
        self.queue_pane.refresh()
        self.history_pane.refresh()
        tasks = self.store.tasks()
        self.refresh_recent(tasks)
        terminal = {"completed", "failed", "cancelled", "interrupted"}
        for index, count in [
            (1, sum(t["state"] not in terminal for t in tasks)),
            (2, sum(t["state"] in terminal for t in tasks)),
        ]:
            self.nav_buttons[index].badge = count
            self.nav_buttons[index].update()
        from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent

        for task in tasks:
            previous = self.announced_states.get(task["id"])
            if previous != task["state"] and task["state"] in {"ready", "completed", "failed", "interrupted"}:
                if QAccessible.isActive():
                    announcement = QAccessibleAnnouncementEvent(
                        self, f"{task['title'][:80] or '作品'}，{STATES[task['state']]}"
                    )
                    announcement.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
                    QAccessible.updateAccessibility(announcement)
            self.announced_states[task["id"]] = task["state"]
        self.statusBar().showMessage(
            f"{len(self.service.running)} 项处理中 · {sum(t['state'] == 'queued' for t in tasks)} 项排队"
        )

    def change_theme(self):
        from PySide6.QtWidgets import QApplication

        value = self.theme.currentData()
        self.store.set_setting("theme", value)
        apply_theme(QApplication.instance(), value)

    def refresh_icons(self):
        for navigation in self.nav_buttons:
            navigation.update()
        if self.isVisible():
            set_window_dark_mode(
                int(self.winId()),
                not self.theme_manager.contrast and self.palette().window().color().lightness() < 128,
            )

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "theme_manager"):
            self.refresh_icons()

    def focus_search(self):
        if self.pages.currentIndex() in {1, 2}:
            pane = self.queue_pane if self.pages.currentIndex() == 1 else self.history_pane
            pane.search.setFocus()
            pane.search.selectAll()

    def export_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出诊断记录", "MediaDownloader-diagnostics.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        diagnostic_report(self.store, self.service.engine), ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
                self.statusBar().showMessage("诊断记录已导出。", 5000)
            except OSError:
                QMessageBox.warning(self, "无法导出", "无法写入所选文件，请检查位置和权限。")

    def refresh_update(self):
        from .engine import tool_versions
        from .presentation import byte_size

        manager = self.updates
        configured = bool(manager and manager.engines.trust.configured)
        busy = bool(manager and manager.busy)
        pinned = self.store.setting("engine_update_locked", False)
        self.update_check.setEnabled(configured and not busy)
        self.update_install.setEnabled(bool(manager and manager.status == "available" and not pinned))
        state = manager.engines.state() if manager else {"current": "bundled", "last_good": "bundled"}
        self.update_rollback.setEnabled(
            bool(manager and not busy and not pinned and state["current"] != state["last_good"])
        )
        self.update_cancel.setEnabled(
            bool(manager and manager.status in {"checking", "downloading", "waiting"})
        )
        self.update_auto.setEnabled(configured)
        self.update_install.setVisible(bool(manager and manager.status == "available"))
        self.update_cancel.setVisible(
            bool(manager and manager.status in {"checking", "downloading", "waiting"})
        )
        if hasattr(self, "kernel_version"):
            self.kernel_version.setText(self.service.engine.version)
            self.update_status.setText(
                "更新源已配置" if configured else "尚未配置更新源，当前使用随应用提供的内核。"
            )
        self.update_pin.setEnabled(bool(manager and manager.status not in {"switching", "recovering"}))
        if manager:
            text = manager.message
            if manager.engines.trust.local_feed:
                text = "本地测试更新源 · " + text
            if manager.status == "downloading":
                text += f"\n{byte_size(manager.progress[0])} / {byte_size(manager.progress[1])}"
            self.update_info.setText(text)
            manifest = manager.manifest
            self.update_notes.setText(
                f"候选内核：{manifest['engine_version']} · {byte_size(manifest['size_bytes'])}\n"
                + "\n".join(manifest["notes"])
                if manifest
                else ""
            )
        self.update_info.setVisible(configured)
        engine = self.service.engine
        self.engine_version_info.setText(
            f"客户端  {__version__}\n内核  {engine.version}\nParseHub  {engine.upstream_sha[:7]}"
        )
        versions = tool_versions(engine)
        if versions:
            self.tool_info.setText("\n".join(f"{name}  {value}" for name, value in versions.items()))

    def rollback_engine(self):
        if self.updates and confirm_action(
            self,
            "回滚内核",
            "切换到上一版本内核？",
            "回滚内核",
            "当前任务结束后切换，任务记录和已下载文件会保留。",
        ):
            self.updates.rollback()

    def pin_engine(self, pinned):
        self.store.set_setting("engine_update_locked", pinned)
        if pinned and self.updates:
            self.updates.cancel()
        self.refresh_update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "nav_names"):
            return
        compact = self.width() < 1000
        self.navigation.setFixedWidth(64 if compact else 208)
        self.version_label.setVisible(not compact)
        self.brand.setVisible(not compact)
        for nav_button in self.nav_buttons:
            nav_button.compact = compact
            nav_button.setToolTip(nav_button.text() if compact else "")
            nav_button.update()

    def load_connection(self):
        from .platforms import PLATFORMS

        platform = self.platform.currentData()
        self.proxy.clear()
        self.cookie.clear()
        saved = bool(self.store.setting(f"{platform}.cookie"))
        proxy = bool(self.store.setting(f"{platform}.proxy"))
        self.connection_info.setText(
            (PLATFORMS[platform].credential_hint + "\n" if PLATFORMS[platform].credential_hint else "")
            + f"Cookie：{'已加密保存' if saved else '未设置'} · 代理：{'已设置' if proxy else '直连'}。"
            "留空 Cookie 不会删除凭据；保存时代理留空则改为直连。"
        )

    def save_connection(self):
        from urllib.parse import urlsplit

        value = self.proxy.text().strip()
        if value and (
            urlsplit(value).scheme not in {"http", "https", "socks5", "socks5h"}
            or not urlsplit(value).hostname
        ):
            QMessageBox.warning(self, "代理地址无效", "请输入 http、https 或 socks5 代理地址。")
            return
        try:
            platform = self.platform.currentData()
            self.store.set_setting(f"{platform}.proxy", protect(value).hex() if value else None)
            if self.cookie.text().strip():
                self.store.set_setting(f"{platform}.cookie", protect(self.cookie.text().strip()).hex())
            self.load_connection()
        except OSError:
            QMessageBox.warning(self, "无法保存", "Windows 凭据加密失败，未写入明文凭据。")

    def delete_cookie(self):
        self.store.set_setting(f"{self.platform.currentData()}.cookie", None)
        self.load_connection()

    def closeEvent(self, event):
        if self.service.running:
            if not confirm_action(self, "退出应用", "仍有任务在运行，是否退出？", "取消任务并退出"):
                event.ignore()
                return
        if self.updates:
            self.updates.shutdown()
        if hasattr(self, "capability_reader"):
            self.capability_reader.shutdown()
        self.service.shutdown()
        event.accept()
