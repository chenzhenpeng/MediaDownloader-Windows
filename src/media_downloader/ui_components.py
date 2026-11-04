"""Small Windows-style surfaces, with native Qt focus and accessibility semantics."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def confirm_action(parent, title, text, action, explanation=""):
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setText(text)
    if explanation:
        dialog.setInformativeText(explanation)
    accept = dialog.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    layout = dialog.layout()
    layout.addItem(QSpacerItem(360, 0), layout.rowCount(), 0, 1, layout.columnCount())
    dialog.exec()
    return dialog.clickedButton() == accept


def label(text="", role="", *, wrap=True):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setObjectName(role)
    return widget


def glyph_font(size=16):
    font = QFont("Segoe Fluent Icons")
    font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    font.setPixelSize(size)
    return font


class ContentIcon(QWidget):
    """Fixed optical box for content icons; independent of font fallback/baselines."""

    def __init__(self, kind="file", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(24, 24)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                self.palette().text().color(),
                1.25,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if self.kind == "folder":
            path.moveTo(3, 7)
            path.lineTo(3, 5.5)
            path.quadTo(3, 4, 4.5, 4)
            path.lineTo(9, 4)
            path.lineTo(11.5, 7)
            path.lineTo(19.5, 7)
            path.quadTo(21, 7, 21, 8.5)
            path.lineTo(21, 18.5)
            path.quadTo(21, 20, 19.5, 20)
            path.lineTo(4.5, 20)
            path.quadTo(3, 20, 3, 18.5)
            path.closeSubpath()
            path.moveTo(3, 9)
            path.lineTo(21, 9)
        else:
            path.moveTo(7, 3)
            path.lineTo(14, 3)
            path.lineTo(19, 8)
            path.lineTo(19, 19.5)
            path.quadTo(19, 21, 17.5, 21)
            path.lineTo(7, 21)
            path.quadTo(5.5, 21, 5.5, 19.5)
            path.lineTo(5.5, 4.5)
            path.quadTo(5.5, 3, 7, 3)
            path.moveTo(14, 3)
            path.lineTo(14, 8)
            path.lineTo(19, 8)
        painter.drawPath(path)


class ComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().buttonText().color(), 1.25))
        x, y = self.width() - 17, self.height() / 2
        path = QPainterPath()
        path.moveTo(x - 4, y - 2)
        path.lineTo(x, y + 2)
        path.lineTo(x + 4, y - 2)
        painter.drawPath(path)


class ExpanderHeader(QToolButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            color = self.palette().text().color()
            color.setAlpha(8)
            painter.fillRect(self.rect(), color)
        painter.setPen(self.palette().text().color())
        painter.setFont(self.font())
        painter.drawText(
            QRectF(18, 0, self.width() - 54, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text()
        )
        x, y = self.width() - 25, self.height() / 2
        path = QPainterPath()
        if self.isChecked():
            path.moveTo(x - 4, y - 2)
            path.lineTo(x, y + 2)
            path.lineTo(x + 4, y - 2)
        else:
            path.moveTo(x - 2, y - 4)
            path.lineTo(x + 2, y)
            path.lineTo(x - 2, y + 4)
        painter.setPen(QPen(self.palette().text().color(), 1.25))
        painter.drawPath(path)
        if self.hasFocus():
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 4, 4)


def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        gradient = QLinearGradient(0, 0, 56, 64)
        gradient.setColorAt(0, QColor("#2997ee"))
        gradient.setColorAt(1, QColor("#0759aa"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
        pen = QPen(
            QColor("white"), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
        )
        painter.setPen(pen)
        painter.drawLine(32, 16, 32, 38)
        path = QPainterPath()
        path.moveTo(23, 30)
        path.lineTo(32, 39)
        path.lineTo(41, 30)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(18, 42)
        path.lineTo(18, 47)
        path.lineTo(46, 47)
        path.lineTo(46, 42)
        painter.drawPath(path)
        painter.end()
        icon.addPixmap(canvas)
    return icon


class NavigationButton(QAbstractButton):
    def __init__(self, text, glyph, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.glyph, self.compact, self.badge = glyph, False, 0
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(184, 40)

    def paintEvent(self, event):
        palette = self.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected, hover = self.isChecked(), self.underMouse()
        contrast = getattr(getattr(QApplication.instance(), "theme_manager", None), "contrast", False)
        accent = palette.highlight().color()
        if selected or hover:
            color = QColor(palette.highlight().color() if contrast else palette.windowText().color())
            if not contrast:
                color.setAlpha(18 if selected else 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 5, 5)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(0, 12, 3, 16), 1.5, 1.5)
        painter.setPen(
            palette.highlightedText().color()
            if contrast and (selected or hover)
            else palette.windowText().color()
        )
        painter.setFont(glyph_font())
        painter.drawText(QRectF(12, 0, 20, 40), Qt.AlignmentFlag.AlignCenter, self.glyph)
        if not self.compact:
            font = self.font()
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.drawText(QRectF(44, 0, self.width() - 72, 40), Qt.AlignmentFlag.AlignVCenter, self.text())
            if self.badge:
                painter.setFont(self.font())
                painter.setPen(
                    palette.highlightedText().color()
                    if contrast and (selected or hover)
                    else palette.placeholderText().color()
                )
                painter.drawText(
                    QRectF(self.width() - 30, 0, 24, 40),
                    Qt.AlignmentFlag.AlignCenter,
                    str(self.badge) if self.badge < 100 else "99+",
                )
        if self.hasFocus() and getattr(self, "keyboard_focus", False):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 3, -2, -3), 4, 4)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() in {
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        }
        self.update()
        super().focusInEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.keyboard_focus = False
        self.update()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            items = self.parentWidget().findChildren(
                NavigationButton, options=Qt.FindChildOption.FindDirectChildrenOnly
            )
            step = -1 if event.key() == Qt.Key.Key_Up else 1
            target = items[max(0, min(len(items) - 1, items.index(self) + step))]
            target.setFocus(Qt.FocusReason.TabFocusReason)
            target.click()
            event.accept()
            return
        super().keyPressEvent(event)


class ToggleSwitch(QCheckBox):
    def __init__(self, name=""):
        super().__init__()
        self.setAccessibleName(name)
        self.setFixedSize(42, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        track = palette.highlight().color() if self.isChecked() else palette.mid().color()
        painter.setBrush(track)
        painter.setPen(QPen(palette.windowText().color() if not self.isChecked() else track, 1))
        painter.drawRoundedRect(QRectF(2, 5, 36, 18), 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.highlightedText() if self.isChecked() else palette.window())
        painter.drawEllipse(QRectF(23 if self.isChecked() else 5, 8, 12, 12))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette.highlight().color(), 2))
            painter.drawRoundedRect(QRectF(0, 1, 41, 24), 4, 4)


class SettingRow(QFrame):
    def __init__(self, title, description="", control=None, glyph=""):
        super().__init__()
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(16)
        if glyph:
            if glyph in {"\ue8b7", "\ue8a5"}:
                symbol = ContentIcon("folder" if glyph == "\ue8b7" else "file")
            else:
                symbol = label(glyph, "settingGlyph", wrap=False)
                symbol.setFont(glyph_font(18))
                symbol.setFixedSize(24, 24)
                symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(symbol, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(label(title, "bodyStrong"))
        if description:
            texts.addWidget(label(description, "secondary"))
        layout.addLayout(texts, 1)
        if control:
            if isinstance(control, QWidget):
                layout.addWidget(control)
                if not control.accessibleName():
                    control.setAccessibleName(title)
            else:
                layout.addLayout(control)


class Expander(QFrame):
    def __init__(self, title, description="", expanded=False):
        super().__init__()
        self.setObjectName("settingRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle = ExpanderHeader()
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setObjectName("expanderHeader")
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle.setMinimumHeight(54)
        layout.addWidget(self.toggle)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(20, 0, 20, 18)
        self.content.setSpacing(12)
        if description:
            self.content.addWidget(label(description, "secondary"))
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class InfoBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("infoBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self.symbol = label("\ue946")
        self.symbol.setFont(glyph_font())
        self.symbol.setFixedWidth(18)
        layout.addWidget(self.symbol, 0, Qt.AlignmentFlag.AlignTop)
        self.message = label()
        layout.addWidget(self.message, 1)
        self.setVisible(False)

    def setText(self, text):
        self.message.setText(text)
        self.setVisible(bool(text))

    def text(self):
        return self.message.text()


class LinkInput(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        data = event.mimeData()
        if data.hasUrls():
            urls = [url.toString() for url in data.urls() if url.scheme() in {"http", "https"}]
            if urls:
                self.insertPlainText("\n".join(urls))
                event.acceptProposedAction()
            return
        super().dropEvent(event)


def command_button(text, slot, *, primary=False):
    widget = QPushButton(text)
    widget.setObjectName("primary" if primary else "command")
    widget.setMinimumHeight(34)
    widget.clicked.connect(slot)
    return widget
