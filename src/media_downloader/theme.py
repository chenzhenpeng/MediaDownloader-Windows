"""Windows color preferences and contrast colors without changing system settings."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette


def system_appearance():
    dark, contrast = False, False
    colors = None
    if os.name == "nt":
        import ctypes
        import winreg
        from ctypes import wintypes

        class HighContrast(ctypes.Structure):
            _fields_ = [("size", wintypes.UINT), ("flags", wintypes.DWORD), ("scheme", wintypes.LPWSTR)]

        user = ctypes.WinDLL("user32")
        status = HighContrast(ctypes.sizeof(HighContrast), 0, None)
        if user.SystemParametersInfoW(0x42, status.size, ctypes.byref(status), 0):
            contrast = bool(status.flags & 1)
        if contrast:

            def color(index):
                value = user.GetSysColor(index)
                return f"#{value & 255:02x}{value >> 8 & 255:02x}{value >> 16 & 255:02x}"

            colors = tuple(color(i) for i in (5, 8, 13, 14, 17))
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                dark = not bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
        except OSError:
            pass
    return dark, contrast, colors


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self, app):
        super().__init__(app)
        self.app, self.preference, self.fingerprint = app, "system", None
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def set_preference(self, preference):
        self.preference = preference if preference in {"system", "light", "dark"} else "system"
        self.fingerprint = None
        self.refresh()

    def refresh(self):
        appearance = system_appearance()
        fingerprint = (self.preference, appearance)
        if self.fingerprint == fingerprint:
            return
        self.fingerprint = fingerprint
        dark, contrast, colors = appearance
        self.contrast = contrast
        if self.preference != "system":
            dark = self.preference == "dark"
        if contrast:
            panel, text, accent, on_accent, muted = colors
            surface, border, selection = panel, text, accent
            content, hover, control_border = panel, accent, text
        elif dark:
            panel, surface, border = "#202020", "#323232", "#3d3d3d"
            content, hover, control_border = "#272727", "#3b3b3b", "#6b6b6b"
            text, muted, selection = "#ffffff", "#cecece", "#383838"
            accent, on_accent = "#60cdff", "#002b42"
        else:
            panel, surface, border = "#f3f3f3", "#ffffff", "#e5e5e5"
            content, hover, control_border = "#fafafa", "#f2f2f2", "#c8c8c8"
            text, muted, selection = "#1a1a1a", "#5d5d5d", "#e7e7e7"
            accent, on_accent = "#005fb8", "#ffffff"
        palette = QPalette()
        for role, value in {
            QPalette.ColorRole.Window: panel,
            QPalette.ColorRole.Base: surface,
            QPalette.ColorRole.AlternateBase: panel,
            QPalette.ColorRole.Button: surface,
            QPalette.ColorRole.WindowText: text,
            QPalette.ColorRole.Text: text,
            QPalette.ColorRole.ButtonText: text,
            QPalette.ColorRole.Highlight: accent,
            QPalette.ColorRole.HighlightedText: on_accent,
            QPalette.ColorRole.ToolTipBase: surface,
            QPalette.ColorRole.ToolTipText: text,
            QPalette.ColorRole.PlaceholderText: muted,
            QPalette.ColorRole.Link: accent,
            QPalette.ColorRole.Mid: control_border,
            QPalette.ColorRole.Dark: border,
        }.items():
            palette.setColor(role, QColor(value))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(muted))
        self.app.setPalette(palette)
        self.app.setStyleSheet(f"""
            QMainWindow, QWidget#shell, QWidget#navigation {{background:{panel};color:{text};}}
            QStackedWidget#contentSurface {{
                background:{content};border:1px solid {border};border-radius:8px;}}
            QScrollArea, QWidget#page, QWidget#scrollBody {{background:transparent;border:0;}}
            QLabel {{color:{text};background:transparent;}}
            QLabel#heading {{font-size:28px;font-weight:400;}}
            QLabel#section {{font-size:16px;font-weight:400;}}
            QLabel#brand {{font-size:14px;font-weight:400;}}
            QLabel#bodyStrong {{font-weight:400;}}
            QLabel#secondary, QLabel#caption {{color:{muted};}}
            QLabel#caption {{font-size:12px;}}
            QLabel#badge {{
                color:{muted};border:1px solid {border};border-radius:4px;padding:2px 6px;font-size:11px;}}
            QFrame#card, QFrame#settingRow {{
                background:{surface};border:1px solid {border};border-radius:7px;}}
            QFrame#linkComposer {{background:transparent;border:0;}}
            QFrame#emptyListing {{background:transparent;border:0;}}
            QFrame#recentRow {{background:transparent;border:0;
                border-bottom:1px solid {border};border-radius:0;}}
            QFrame#detailPanel {{background:{surface};border:1px solid {border};border-radius:7px;}}
            QFrame#infoBar {{background:{surface};border:1px solid {border};border-radius:5px;}}
            QFrame#previewWell {{background:{content};border:0;border-radius:5px;}}
            QPushButton, QToolButton {{color:{text};background:{surface};border:1px solid {control_border};
                border-radius:4px;padding:6px 12px;}}
            QPushButton:hover, QToolButton:hover {{background:{hover};}}
            QPushButton:pressed, QToolButton:pressed {{background:{selection};}}
            QPushButton:disabled, QToolButton:disabled {{
                color:{muted};border-color:{border};background:{content};}}
            QPushButton:focus, QToolButton:focus {{border:1px solid {accent};}}
            QPushButton#primary:enabled {{background:{accent};color:{on_accent};border:1px solid {accent};}}
            QPushButton#primary:hover {{background:{accent};border:1px solid {accent};}}
            QPushButton#primary:focus {{border:1px solid {text};}}
            QPushButton#subtle, QPushButton#command, QToolButton#command, QToolButton#expanderHeader {{
                background:transparent;
                border:1px solid transparent;border-radius:4px;}}
            QPushButton#subtle:hover, QPushButton#command:hover, QToolButton#command:hover,
            QToolButton#expanderHeader:hover {{
                background:{hover};}}
            QPushButton#subtle:focus, QPushButton#command:focus, QToolButton#command:focus,
            QToolButton#expanderHeader:focus {{
                border-color:{accent};}}
            QToolButton#expanderHeader {{padding:12px 18px;text-align:left;}}
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{background:{surface};color:{text};
                border:1px solid {control_border};
                border-radius:4px;padding:7px 10px;}}
            QLineEdit:focus, QPlainTextEdit:focus {{border:1px solid {accent};}}
            QLineEdit#directoryInput {{border:0;background:transparent;padding:0;}}
            QLineEdit#directoryInput:focus {{border-bottom:1px solid {accent};}}
            QComboBox, QSpinBox {{min-height:20px;}}
            QToolButton::menu-indicator {{image:none;}}
            QComboBox::drop-down {{width:26px;border:0;}}
            QTableWidget {{
                background:{surface};color:{text};border:0;selection-background-color:{selection};}}
            QTableWidget::item {{border:0;padding:0;}}
            QTableWidget::item:selected {{
                background:{selection};color:{text if not contrast else on_accent};}}
            QTableWidget:focus {{border:0;}}
            QHeaderView::section {{background:{content};color:{muted};font-weight:400;font-size:12px;
                padding:10px 8px;border:0;border-bottom:1px solid {border};text-align:left;}}
            QHeaderView {{border:0;}}
            QProgressBar {{border:0;border-radius:2px;background:{border};text-align:center;color:{text};}}
            QProgressBar::chunk {{background:{accent};border-radius:2px;}}
            QSplitter::handle {{background:transparent;}}
            QScrollBar:vertical {{background:transparent;width:10px;margin:3px 1px;}}
            QScrollBar::handle:vertical {{
                background:{control_border};min-height:32px;border-radius:4px;margin:0 2px;}}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{height:0;}}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{background:transparent;}}
            QMenu {{
                background:{surface};color:{text};border:1px solid {border};padding:4px;border-radius:6px;}}
            QMenu::item {{padding:7px 18px;border-radius:4px;}}
            QMenu::item:selected {{background:{selection};}}
            QMenu::item:disabled {{color:{muted};}}
            QStatusBar {{background:{panel};color:{muted};font-size:12px;border:0;}}
        """)
        self.changed.emit()


def apply_theme(app, preference="system"):
    from .localization import install_chinese

    install_chinese(app)
    font = QFont("Segoe UI Variable Text", 10)
    font.setPixelSize(14)
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"])
    font.setWeight(QFont.Weight.Normal)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)
    manager = getattr(app, "theme_manager", None)
    if manager is None:
        manager = app.theme_manager = ThemeManager(app)
    manager.set_preference(preference)
    return manager
