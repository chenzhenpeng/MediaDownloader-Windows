"""Rasterize the versioned vector mark for Windows shell sizes."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    root = Path(__file__).resolve().parents[1]
    assets = root / "native/MediaDownloader/Assets"
    renderer = QSvgRenderer(str(assets / "AppIcon.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid app mark")
    output = root / "build/icons"
    output.mkdir(parents=True, exist_ok=True)
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    rasters = {}
    for size in sizes:
        canvas = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        target = output / f"app-icon-{size}.png"
        assert canvas.save(str(target))
        rasters[size] = target
    with Image.open(rasters[256]) as source:
        source.save(
            assets / "AppIcon.ico",
            sizes=[(size, size) for size in sizes],
            append_images=[Image.open(rasters[size]).copy() for size in sizes if size != 256],
        )
        source.save(assets / "AppIcon.png")
        source.save(output / "media-downloader.png")
    (output / "media-downloader.ico").write_bytes((assets / "AppIcon.ico").read_bytes())


if __name__ == "__main__":
    main()
