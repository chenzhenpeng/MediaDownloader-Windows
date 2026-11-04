import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Qt allows one application lifetime per process. Keep it alive across pool tests.
    from PySide6.QtCore import QCoreApplication, qInstallMessageHandler

    previous = qInstallMessageHandler(
        lambda kind, context, message: os.write(2, (message + "\n").encode("utf-8"))
    )
    application = QCoreApplication.instance() or QCoreApplication([])
    yield application
    application.processEvents()
    qInstallMessageHandler(previous)
