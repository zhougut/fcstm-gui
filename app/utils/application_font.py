"""Install the bundled cross-platform CJK application font."""

from __future__ import unicode_literals

import sys
from pathlib import Path

from PyQt5 import QtGui, QtWidgets


FONT_FILENAME = "NotoSansCJKsc-Regular.otf"
FONT_SHA256 = "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"
EXPECTED_FAMILY = "Noto Sans CJK SC"
_font_id = None


def bundled_font_path():
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "app" / "resources" / "fonts" / FONT_FILENAME
    return Path(__file__).resolve().parents[1] / "resources" / "fonts" / FONT_FILENAME


def install_application_font(app=None):
    global _font_id
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before installing the bundled font")
    if _font_id is None:
        path = bundled_font_path()
        if not path.is_file():
            return None
        _font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
    if _font_id < 0:
        return None
    families = tuple(QtGui.QFontDatabase.applicationFontFamilies(_font_id))
    if EXPECTED_FAMILY not in families:
        return None
    font = app.font()
    font.setFamily(EXPECTED_FAMILY)
    app.setFont(font)
    return EXPECTED_FAMILY
