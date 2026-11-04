"""Keep Qt-owned menus and standard buttons in the application's Chinese language."""

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator


def install_chinese(app):
    if getattr(app, "chinese_translator", None) is not None:
        return True
    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    locations = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))]
    if getattr(sys, "frozen", False):
        locations.insert(0, Path(sys._MEIPASS) / "translations")
    translator = QTranslator(app)
    for location in locations:
        if translator.load(str(location / "qtbase_zh_CN.qm")):
            app.installTranslator(translator)
            app.chinese_translator = translator
            return True
    return False
