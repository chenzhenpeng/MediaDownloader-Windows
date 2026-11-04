"""Task command surface and readable media rows, with optional progressive details."""

from __future__ import annotations

import base64
import html
from datetime import datetime

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .presentation import (
    PLATFORMS,
    TERMINAL,
    byte_size,
    filtered_tasks,
    media_description,
    preview_data,
    progress_text,
)
from .ui_components import ComboBox, Expander, InfoBar, command_button, glyph_font, label


def thumbnail_pixmap(encoded):
    if not isinstance(encoded, str) or len(encoded) > 160_000:
        return QPixmap()
    try:
        data = QByteArray(base64.b64decode(encoded, validate=True))
    except ValueError:
        return QPixmap()
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 160_000:
        return QPixmap()
    return QPixmap.fromImage(reader.read())


def detail_title(text, font, width=240):
    text = text.replace("\n", " ")
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    first = layout.createLine()
    if not first.isValid():
        layout.endLayout()
        return text
    first.setLineWidth(width)
    length = first.textLength()
    layout.endLayout()
    if length >= len(text):
        return text
    return (
        text[:length].rstrip()
        + "\n"
        + QFontMetrics(font).elidedText(text[length:].strip(), Qt.TextElideMode.ElideRight, width)
    )


class MediaDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        palette, rect = option.palette, QRectF(option.rect)
        accent = QApplication.palette().highlight()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        contrast = getattr(getattr(QApplication.instance(), "theme_manager", None), "contrast", False)
        painter.fillRect(rect, palette.base())
        if selected:
            bg = accent.color()
            if not contrast:
                bg.setAlpha(32)
            painter.fillRect(rect, bg)
            if index.column() == 0:
                painter.fillRect(QRectF(rect.left(), rect.top() + 12, 3, rect.height() - 24), accent)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            bg = palette.windowText().color()
            bg.setAlpha(8)
            painter.fillRect(rect, bg)
        foreground = palette.highlightedText().color() if selected and contrast else palette.text().color()
        muted = foreground if selected and contrast else palette.placeholderText().color()
        painter.setPen(QPen(palette.dark().color(), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setFont(option.font)
        painter.setPen(foreground)
        row = index.data(Qt.ItemDataRole.UserRole + 1) or {}
        if index.column() == 0:
            thumb_rect = QRectF(rect.left() + 12, rect.top() + 16, 56, 44)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.window())
            painter.drawRoundedRect(thumb_rect, 4, 4)
            pixmap = index.data(Qt.ItemDataRole.UserRole + 2)
            if isinstance(pixmap, QPixmap) and not pixmap.isNull():
                ratio = min(56 / pixmap.width(), 44 / pixmap.height())
                width, height = pixmap.width() * ratio, pixmap.height() * ratio
                painter.drawPixmap(
                    QRectF(
                        thumb_rect.center().x() - width / 2,
                        thumb_rect.center().y() - height / 2,
                        width,
                        height,
                    ),
                    pixmap,
                    QRectF(pixmap.rect()),
                )
            else:
                painter.setFont(glyph_font(22))
                painter.setPen(muted)
                painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "\ue8a5")
            text_rect = QRectF(rect.left() + 80, rect.top() + 15, max(0, rect.width() - 94), 24)
            font = option.font
            font.setWeight(font.Weight.Normal)
            painter.setFont(font)
            painter.setPen(foreground)
            text = painter.fontMetrics().elidedText(
                index.data() or "", Qt.TextElideMode.ElideRight, int(text_rect.width())
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
            font.setWeight(font.Weight.Normal)
            painter.setFont(font)
            painter.setPen(muted)
            subtitle = painter.fontMetrics().elidedText(
                row.get("subtitle", ""), Qt.TextElideMode.ElideRight, int(text_rect.width())
            )
            painter.drawText(text_rect.translated(0, 23), Qt.AlignmentFlag.AlignVCenter, subtitle)
        elif index.column() == 2:
            color = foreground
            if not contrast:
                dark = palette.window().color().lightness() < 128
                if row.get("state") == "completed":
                    color = QColor("#6ccb5f" if dark else "#0f7b0f")
                elif row.get("state") in {"failed", "interrupted"}:
                    color = QColor("#ff99a4" if dark else "#c42b1c")
            painter.setPen(color)
            painter.drawText(rect.adjusted(8, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, index.data() or "")
        else:
            painter.setPen(muted)
            painter.drawText(
                rect.adjusted(8, -8 if row.get("percent") is not None else 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter,
                index.data() or "",
            )
            if row.get("percent") is not None:
                track = QRectF(rect.left() + 8, rect.bottom() - 22, rect.width() - 22, 3)
                painter.fillRect(track, palette.mid())
                painter.fillRect(
                    QRectF(track.left(), track.top(), track.width() * row["percent"] / 100, 3),
                    accent,
                )
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(accent.color(), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        painter.restore()


class TaskPane(QWidget):
    def __init__(self, window, history):
        super().__init__()
        from .ui import STATES

        self.window, self.history, self.states = window, history, STATES
        self.detail_key, self.task_id = None, None
        self.thumbnail_cache, self.in_dialog = {}, False
        self.detail_requested = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.search_bar = QWidget()
        search_row = QHBoxLayout(self.search_bar)
        search_row.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索作品或平台")
        self.search.setAccessibleName("搜索历史" if history else "搜索下载队列")
        self.search.setClearButtonEnabled(True)
        search_row.addWidget(self.search, 1)
        self.filter = ComboBox()
        self.filter.setMinimumWidth(132)
        self.filter.setAccessibleName("任务状态筛选")
        self.filter.addItem("全部状态", "")
        for state in (
            ["completed", "failed", "interrupted", "cancelled"]
            if history
            else ["queued", "parsing", "ready", "downloading", "finalizing", "cancelling"]
        ):
            self.filter.addItem(STATES[state], state)
        search_row.addWidget(self.filter)
        outer.addWidget(self.search_bar)
        self.toolbar = QWidget()
        toolbar = QHBoxLayout(self.toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        self.start = command_button("打开文件" if history else "开始下载", self.primary_action, primary=True)
        self.start.setMinimumWidth(104)
        toolbar.addWidget(self.start)
        self.cancel = command_button("取消任务", lambda: self.act("cancel"))
        self.cancel.setVisible(not history)
        toolbar.addWidget(self.cancel)
        self.open_folder = command_button("打开文件夹", lambda: self.act("open"))
        toolbar.addWidget(self.open_folder)
        toolbar.addStretch()
        self.details_button = command_button("作品详情", self.show_details)
        toolbar.addWidget(self.details_button)
        self.more = QToolButton()
        self.more.setText("\ue712")
        self.more.setFont(glyph_font())
        self.more.setFixedSize(36, 34)
        self.more.setToolTip("更多操作")
        self.more.setObjectName("command")
        self.more.setAccessibleName("更多任务操作")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.more)
        self.open_file = self.menu.addAction("打开文件", lambda: self.act("file"))
        self.redownload = self.menu.addAction("重新下载", lambda: self.act("retry"))
        self.menu.addSeparator()
        self.menu.addAction("复制任务编号", self.copy_id)
        self.remove = self.menu.addAction("移除记录…", lambda: self.act("remove"))
        self.remove.setVisible(history)
        self.more.setMenu(self.menu)
        toolbar.addWidget(self.more)
        outer.addWidget(self.toolbar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(12)
        listing = self.listing = QFrame()
        listing.setObjectName("card")
        listing_box = self.listing_box = QVBoxLayout(listing)
        listing_box.setContentsMargins(1, 1, 1, 1)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["作品", "平台", "状态", "文件大小", "结束时间"]
            if history
            else ["作品", "平台", "状态", "进度", ""]
        )
        self.table.setColumnHidden(4, not history)
        self.table.setColumnWidth(4, 138)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.hideColumn(1)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(3, 104)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setItemDelegate(MediaDelegate(self.table))
        self.table.setAccessibleName("历史记录列表" if history else "下载队列列表")
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        listing_box.addWidget(self.table, 1)
        self.empty_panel = QWidget()
        self.empty_panel.setMaximumSize(480, 260)
        empty_box = QVBoxLayout(self.empty_panel)
        empty_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        symbol = label("\ue8a5" if history else "\ue896")
        symbol.setFont(glyph_font(40))
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(symbol)
        self.empty = label("", "section")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(self.empty)
        self.empty_help = label("", "secondary")
        self.empty_help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_help.setMinimumWidth(280)
        self.empty_help.setMaximumWidth(420)
        empty_box.addWidget(self.empty_help)
        add = self.empty_action = command_button("添加下载", self.empty_action_clicked, primary=True)
        empty_box.addWidget(add, 0, Qt.AlignmentFlag.AlignCenter)
        listing_box.addWidget(self.empty_panel, 1, Qt.AlignmentFlag.AlignHCenter)
        self.splitter.addWidget(listing)
        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("detailPanel")
        self.detail_panel.setMinimumWidth(290)
        self.detail_panel.setMaximumWidth(360)
        detail_outer = QVBoxLayout(self.detail_panel)
        detail_outer.setContentsMargins(16, 16, 16, 12)
        detail_outer.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label("作品详情", "section"))
        heading.addStretch()
        close = command_button("关闭", self.hide_details)
        heading.addWidget(close)
        detail_outer.addLayout(heading)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail = QWidget()
        detail.setObjectName("scrollBody")
        box = QVBoxLayout(detail)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.title = label("", "bodyStrong")
        self.title.setMaximumHeight(48)
        box.addWidget(self.title)
        self.full_title = label("", wrap=True)
        self.full_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.full_title.hide()
        box.addWidget(self.full_title)
        title_actions = QHBoxLayout()
        self.expand_title = command_button("展开标题", self.toggle_title)
        title_actions.addWidget(self.expand_title)
        title_actions.addWidget(command_button("复制标题", self.copy_title))
        title_actions.addStretch()
        box.addLayout(title_actions)
        self.summary = label("", "secondary")
        box.addWidget(self.summary)
        self.preview_well = QFrame()
        self.preview_well.setObjectName("previewWell")
        self.preview_well.setFixedHeight(118)
        self.artwork = QHBoxLayout(self.preview_well)
        self.artwork.setContentsMargins(8, 4, 8, 4)
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Keep status, repair advice and output location above optional artwork.
        self.media = label("")
        self.format = QComboBox(self.detail_panel)
        self.format.addItem("当前可用格式", "current")
        self.format.setEnabled(False)
        self.format.hide()  # No disabled selector for formats the kernel cannot offer.
        self.bar = QProgressBar()
        self.bar.setAccessibleName("任务进度")
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.progress = label("", "secondary")
        self.message = InfoBar()
        box.addWidget(self.message)
        box.addWidget(label("保存位置", "caption"))
        self.destination = label("", "secondary", wrap=False)
        box.addWidget(self.destination)
        self.connection = command_button("管理平台连接", self.manage_connection)
        box.addWidget(self.connection)
        box.addWidget(self.bar)
        box.addWidget(self.progress)
        self.metadata_heading = label("媒体信息", "caption")
        box.addWidget(self.metadata_heading)
        box.addWidget(self.media)
        box.addWidget(self.preview_well)
        advanced = Expander("执行记录与诊断")
        self.attempts = label("", "caption")
        advanced.content.addWidget(self.attempts)
        box.addWidget(advanced)
        box.addStretch()
        self.detail_scroll.setWidget(detail)
        detail_outer.addWidget(self.detail_scroll, 1)
        self.splitter.addWidget(self.detail_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([620, 320])
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        outer.addWidget(self.splitter, 1)
        self.search.textChanged.connect(self.refresh)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self.show_selection)
        self.table.itemActivated.connect(self.show_details)
        self.show_selection()

    def empty_action_clicked(self):
        if self.search.text() or self.filter.currentData():
            self.search.clear()
            self.filter.setCurrentIndex(0)
        else:
            self.window.navigate(0)

    def toggle_title(self):
        expanded = not self.full_title.isVisible()
        self.full_title.setVisible(expanded)
        self.title.setVisible(not expanded)
        self.expand_title.setText("收起标题" if expanded else "展开标题")

    def copy_title(self):
        QApplication.clipboard().setText(self.full_title.text())

    def act(self, action):
        self.window.selected_action(self.table, action)

    def primary_action(self):
        task = self.window.store.get(self.task_id) if self.task_id else None
        self.act("file" if task and task["state"] == "completed" else "retry")

    def copy_id(self):
        if self.task_id:
            QApplication.clipboard().setText(self.task_id)

    def context_menu(self, position):
        index = self.table.indexAt(position)
        if index.isValid():
            self.table.selectRow(index.row())
            self.menu.exec(self.table.viewport().mapToGlobal(position))

    def manage_connection(self):
        task = self.window.store.get(self.task_id) if self.task_id else None
        if task:
            index = self.window.platform.findData(task["platform"])
            if index >= 0:
                self.window.platform.setCurrentIndex(index)
        self.window.connection_expander.toggle.setChecked(True)
        self.window.navigate(3)
        self.window.pages.currentWidget().ensureWidgetVisible(self.window.platform)

    def refresh(self, *args):
        table, selected = self.table, self.task_id
        tasks = self.window.store.tasks()
        self.search_bar.setVisible(any((t["state"] in TERMINAL) == self.history for t in tasks))
        rows = filtered_tasks(
            tasks,
            history=self.history,
            query=self.search.text().strip(),
            state=self.filter.currentData(),
        )
        scroll = table.verticalScrollBar().value()
        table.blockSignals(True)
        table.setRowCount(len(rows))
        live_ids = set()
        stats = {
            r[0]: (r[1], r[2])
            for r in self.window.store.db.execute(
                """SELECT a.id,SUM(o.size_bytes),a.finished_at FROM attempts a
            LEFT JOIN outputs o ON o.attempt_id=a.id GROUP BY a.id"""
            )
        }
        for index, task in enumerate(rows):
            live_ids.add(task["id"])
            preview = preview_data(task)
            subtitle = PLATFORMS.get(task["platform"], "—")
            if preview.get("media"):
                subtitle += " · " + media_description(preview["media"][0])
            progress = self.window.service.progress.get(task["id"], {})
            percent = progress.get("percent") if task["state"] == "downloading" else None
            state = task["state"]
            progress_label = (
                f"{percent:g}%"
                if percent is not None
                else {
                    "ready": "待确认",
                    "completed": "已保存",
                    "failed": "可重试",
                    "interrupted": "可重试",
                    "parsing": "解析中",
                    "finalizing": "校验中",
                    "queued": "等待中",
                    "cancelled": "已结束",
                    "cancelling": "取消中",
                    "downloading": "下载中",
                }.get(state, "—")
            )
            values = [
                task["title"] or "正在获取作品信息",
                subtitle,
                "文件无效" if task["error_code"] == "INVALID_SAVED_MEDIA" else self.states.get(state, state),
                progress_label,
            ]
            if self.history:
                size, finished = stats.get(task["attempt_id"], (None, None))
                values[3] = byte_size(size) if size else "—"
                values.append(
                    datetime.fromisoformat(finished).astimezone().strftime("%m-%d %H:%M") if finished else "—"
                )
            cached = self.thumbnail_cache.get(task["id"])
            if not cached or cached[0] != task["preview"]:
                encoded = preview.get("thumbnails", [])
                cached = (task["preview"], thumbnail_pixmap(encoded[0]) if encoded else QPixmap())
                self.thumbnail_cache[task["id"]] = cached
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, task["id"])
                item.setData(
                    Qt.ItemDataRole.UserRole + 1, {"state": state, "percent": percent, "subtitle": subtitle}
                )
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole + 2, cached[1])
                item.setToolTip(html.escape(text))
                table.setItem(index, column, item)
            table.setRowHeight(index, 76)
        self.thumbnail_cache = {key: value for key, value in self.thumbnail_cache.items() if key in live_ids}
        selected_row = next((i for i, t in enumerate(rows) if t["id"] == selected), 0)
        if rows:
            table.selectRow(selected_row)
        table.blockSignals(False)
        table.verticalScrollBar().setValue(scroll)
        table.setVisible(bool(rows))
        self.toolbar.setVisible(bool(rows))
        name = "card" if rows else "emptyListing"
        if self.listing.objectName() != name:
            self.listing.setObjectName(name)
            self.listing.style().unpolish(self.listing)
            self.listing.style().polish(self.listing)
        self.listing_box.setAlignment(Qt.AlignmentFlag(0) if rows else Qt.AlignmentFlag.AlignTop)
        self.empty_panel.setVisible(not rows)
        searching = bool(self.search.text() or self.filter.currentData())
        self.empty_action.setText("清除筛选" if searching else "添加下载")
        self.empty.setText(
            "没有匹配的作品" if searching else "还没有下载记录" if self.history else "准备好下一次下载"
        )
        self.empty_help.setText(
            "试试其他关键词或筛选条件。"
            if searching
            else "完成或结束的任务会显示在这里。"
            if self.history
            else "粘贴链接，预览后开始下载。"
        )
        self.show_selection()
        if not self.in_dialog:
            self.detail_panel.setVisible(bool(rows) and self.width() >= 880 and self.detail_requested)

    def show_selection(self):
        table, store, service = self.table, self.window.store, self.window.service
        item = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        task = store.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        previous_id = self.task_id
        self.task_id = task["id"] if task else None
        if self.task_id != previous_id:
            self.detail_scroll.verticalScrollBar().setValue(0)
            self.full_title.hide()
            self.title.show()
            self.expand_title.setText("展开标题")
        state = task["state"] if task else ""
        available = bool(task and task["id"] not in service.running)
        self.start.setEnabled(
            available and state in {"ready", "failed", "cancelled", "interrupted", "completed"}
        )
        self.start.setText(
            "打开文件"
            if state == "completed"
            else "重试"
            if state in {"failed", "interrupted", "cancelled"}
            else "开始下载"
        )
        self.cancel.setEnabled(bool(task and state in {"queued", "parsing", "ready", "downloading"}))
        self.open_file.setEnabled(state == "completed")
        self.redownload.setEnabled(available and state == "completed")
        self.open_folder.setEnabled(bool(task))
        self.details_button.setEnabled(bool(task))
        self.more.setEnabled(bool(task))
        self.remove.setEnabled(available and task["id"] not in service.pending_removals)
        invalid_output = bool(task and task["error_code"] == "INVALID_SAVED_MEDIA")
        self.connection.setVisible(state in {"failed", "interrupted"} and not invalid_output)
        self.bar.setVisible(state in {"parsing", "downloading", "finalizing", "cancelling"})
        self.progress.setVisible(state == "downloading")
        if not task:
            for widget in (
                self.title,
                self.summary,
                self.media,
                self.progress,
                self.message,
                self.destination,
                self.attempts,
            ):
                widget.setText("")
            self.clear_artwork()
            self.preview_well.hide()
            self.detail_key = None
            return
        full_title = task["title"] or "正在获取作品信息"
        self.full_title.setText(full_title)
        self.title.setText(detail_title(full_title, self.title.font()))
        self.title.setAccessibleName(full_title)
        self.title.setWordWrap(False)
        self.title.setToolTip(html.escape(task["title"] or ""))
        preview = preview_data(task)
        status = "文件无效" if invalid_output else self.states[state]
        self.summary.setText(f"{PLATFORMS.get(task['platform'], '未知平台')} · {status}")
        self.metadata_heading.setText("原解析信息（不代表文件有效）" if invalid_output else "媒体信息")
        self.media.setText(
            "\n".join(media_description(media) for media in preview.get("media", [])[:3])
            + (f"\n共 {preview['media_count']} 项媒体" if preview.get("media_count", 0) > 1 else "")
        )
        dpr = self.devicePixelRatioF()
        key = (task["id"], task["preview"], dpr)
        if self.detail_key != key:
            self.clear_artwork()
            images = preview.get("thumbnails", [])[:3]
            for encoded in images:
                pixmap = thumbnail_pixmap(encoded)
                if not pixmap.isNull():
                    image = QLabel()
                    image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    image.setAccessibleName("作品封面预览")
                    rendered = pixmap.scaled(
                        int((260 if len(images) == 1 else 80) * dpr),
                        int(108 * dpr),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    rendered.setDevicePixelRatio(dpr)
                    image.setPixmap(rendered)
                    self.artwork.addWidget(image)
            self.preview_well.setVisible(self.artwork.count() > 0)
            self.detail_key = key
        progress = service.progress.get(task["id"], {})
        percent = progress.get("percent")
        self.bar.setRange(0, 100 if percent is not None else 0)
        if percent is not None:
            self.bar.setValue(int(percent))
        self.progress.setText(progress_text(progress) if state == "downloading" else "")
        self.message.setText(
            task["error"]
            or {
                "ready": "确认作品后，点击“开始下载”。",
                "finalizing": "正在校验并保存文件，请稍候。",
                "cancelling": "正在取消本次任务。",
            }.get(state, "")
        )
        path = task["final_dir"] or task["output_root"]
        self.destination.setText(self.fontMetrics().elidedText(path, Qt.TextElideMode.ElideMiddle, 270))
        self.destination.setToolTip(html.escape(path))
        attempts = store.attempts(task["id"])
        self.attempts.setText(
            f"任务编号：{task['id']}\n\n"
            + "\n".join(
                f"{'解析' if a['action'] == 'inspect' else '下载'} · "
                f"{self.states.get(a['state'], a['state'])}\n{a['engine_version']}"
                for a in attempts[-6:]
            )
            + (f"\n\n错误码：{task['error_code']}" if task.get("error_code") else "")
        )

    def clear_artwork(self):
        while self.artwork.count():
            item = self.artwork.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_details(self, *args):
        if not self.task_id:
            return
        if self.width() >= 880:
            self.detail_requested = not self.detail_panel.isVisible()
            self.detail_panel.setVisible(self.detail_requested)
            return
        self.in_dialog = True
        dialog = QDialog(self.window)
        dialog.setWindowTitle("作品详情")
        dialog.resize(400, 620)
        layout = QVBoxLayout(dialog)
        self.detail_panel.setMaximumWidth(16777215)
        layout.addWidget(self.detail_panel)
        self.detail_panel.show()
        dialog.exec()
        layout.removeWidget(self.detail_panel)
        self.splitter.addWidget(self.detail_panel)
        self.detail_panel.setMaximumWidth(360)
        self.detail_panel.hide()
        self.in_dialog = False

    def hide_details(self):
        if self.in_dialog:
            self.detail_panel.window().reject()
        else:
            self.detail_requested = False
            self.detail_panel.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "detail_panel") and not self.in_dialog:
            self.detail_panel.setVisible(self.width() >= 880 and bool(self.task_id) and self.detail_requested)
