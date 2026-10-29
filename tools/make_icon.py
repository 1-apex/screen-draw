"""Render the app icon to a multi-size .ico for the Windows build.

Usage:  python tools/make_icon.py assets/icon.ico
"""
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 1x scale, no window needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from PySide6.QtCore import QBuffer
from PySide6.QtWidgets import QApplication

import screen_draw

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def main(out_path):
    app = QApplication([])  # noqa: F841 - Qt needs an app to render pixmaps
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    frames = []
    # Render each size separately so small sizes stay sharp instead of downscaled.
    for size in SIZES:
        pixmap = screen_draw._pixmap(screen_draw.draw_app_icon, "#ffffff", "#ffffff", size)
        buffer = QBuffer()
        buffer.open(QBuffer.WriteOnly)
        pixmap.toImage().save(buffer, "PNG")
        frames.append(Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA"))
    largest = frames[-1]
    largest.save(out_path, format="ICO", sizes=[(s, s) for s in SIZES],
                 append_images=frames[:-1])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "assets/icon.ico")
