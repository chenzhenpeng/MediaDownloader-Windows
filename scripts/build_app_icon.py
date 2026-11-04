"""Render the code-owned app mark at Windows shell icon sizes."""

from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from media_downloader.ui_components import app_icon


def main():
    app = QApplication([])
    output = Path(__file__).resolve().parents[1] / "build/icons"
    output.mkdir(parents=True, exist_ok=True)
    raster = output / "media-downloader.png"
    assert app_icon().pixmap(256, 256).save(str(raster))
    with Image.open(raster) as source:
        source.save(
            output / "media-downloader.ico", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]
        )
    app.quit()


if __name__ == "__main__":
    main()
