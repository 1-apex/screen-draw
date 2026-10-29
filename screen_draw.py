"""Screen Draw - draw over anything on your screen.

A transparent, always-on-top overlay covers the primary monitor and a small
floating toolbar controls it. With draw mode off, mouse clicks pass straight
through to the apps underneath while your drawings stay visible.

The app lives in the system tray; launching it again just brings the toolbar
back instead of starting a second copy.

Run:  python screen_draw.py
"""
import ctypes
import getpass
import math
import os
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

if sys.platform == "win32":
    import winreg

APP_NAME = "Screen Draw"
APP_ID = "1apex.ScreenDraw"  # Windows AppUserModelID, groups the app's taskbar/tray identity
INSTANCE_KEY = f"screen-draw-{getpass.getuser()}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

PEN, HIGHLIGHTER, LINE, ARROW, RECT, ELLIPSE, ERASER = (
    "pen", "highlighter", "line", "arrow", "rect", "ellipse", "eraser",
)
FREEHAND = (PEN, HIGHLIGHTER)

COLORS = ["#ff453a", "#ffd60a", "#30d158", "#0a84ff", "#bf5af2", "#ffffff", "#1c1c1e"]
WIDTHS = {"S": 3, "M": 6, "L": 12}
HIGHLIGHTER_ALPHA = 90
HIGHLIGHTER_SCALE = 4  # highlighter is this many times wider than the pen
ERASER_RADIUS = 10

# Win32 extended window styles used to make the overlay click-through.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


@dataclass
class Stroke:
    """One drawn item. Freehand tools use every point; shapes use first and last."""

    tool: str
    color: QColor
    width: float
    points: list
    _cached_path: QPainterPath | None = field(default=None, repr=False)

    def pen(self) -> QPen:
        color = QColor(self.color)
        width = self.width
        if self.tool == HIGHLIGHTER:
            color.setAlpha(HIGHLIGHTER_ALPHA)
            width *= HIGHLIGHTER_SCALE
        return QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def path(self) -> QPainterPath:
        if self._cached_path is not None:
            return self._cached_path
        path = QPainterPath()
        a, b = self.points[0], self.points[-1]
        if self.tool in FREEHAND:
            path.moveTo(a)
            for pt in self.points[1:]:
                path.lineTo(pt)
            if path.length() == 0:  # a click without moving still leaves a dot
                path.lineTo(a + QPointF(0.5, 0))
        elif self.tool in (LINE, ARROW):
            path.moveTo(a)
            path.lineTo(b)
            if self.tool == ARROW and a != b:
                angle = math.atan2(b.y() - a.y(), b.x() - a.x())
                head = max(12.0, self.width * 4)
                for offset in (math.radians(150), math.radians(-150)):
                    path.moveTo(b)
                    path.lineTo(b + QPointF(math.cos(angle + offset) * head,
                                            math.sin(angle + offset) * head))
        elif self.tool == RECT:
            path.addRect(QRectF(a, b).normalized())
        elif self.tool == ELLIPSE:
            path.addEllipse(QRectF(a, b).normalized())
        return path

    def freeze(self):
        """Cache the path once the stroke is finished; it never changes again."""
        self._cached_path = None
        self._cached_path = self.path()

    def draw(self, painter: QPainter):
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

    def hit(self, point: QPointF) -> bool:
        stroker = QPainterPathStroker()
        stroker.setWidth(self.pen().widthF() + ERASER_RADIUS * 2)
        stroker.setCapStyle(Qt.RoundCap)
        return stroker.createStroke(self.path()).contains(point)


# --- icons ----------------------------------------------------------------
# Every icon is drawn as vector art on a 24x24 grid, so it stays crisp at any
# display scale. `fg` is the line color, `accent` is the current ink color.

ICON_SIZE = 22
ICON_FG = QColor("#c9ccd6")
ICON_FG_ON = QColor("#ffffff")


def _line(color, width=1.8) -> QPen:
    return QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _alpha(color, alpha) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def _poly(*pts) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def draw_cursor(p, fg, accent):
    p.setPen(_line(_alpha(QColor("#000000"), 140), 1.2))
    p.setBrush(fg)
    p.drawPolygon(_poly((6, 3), (6, 19.5), (10.2, 15.4), (13, 21.6),
                        (15.8, 20.4), (13.1, 14.3), (18.6, 14.3)))


def draw_pen(p, fg, accent):
    p.translate(12, 12)
    p.rotate(-45)
    p.setPen(_line(fg, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-7.5, -2.8, 12.5, 5.6), 1, 1)
    p.setBrush(fg)
    p.drawRoundedRect(QRectF(5, -2.8, 3.5, 5.6), 1.2, 1.2)
    p.setBrush(accent)
    p.drawPolygon(_poly((-7.5, -2.8), (-11.8, 0), (-7.5, 2.8)))


def draw_highlighter(p, fg, accent):
    p.setPen(Qt.NoPen)
    p.setBrush(_alpha(accent, 120))
    p.drawRoundedRect(QRectF(2, 18.5, 19, 4), 2, 2)
    p.translate(13, 11)
    p.rotate(-45)
    p.setPen(_line(fg, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-4, -4, 12, 8), 2, 2)
    p.drawPolygon(_poly((-4, -3.2), (-7.5, -2.4), (-7.5, 2.4), (-4, 3.2)))
    p.setBrush(accent)
    p.drawPolygon(_poly((-7.5, -2.4), (-10.5, -0.6), (-10.5, 2.4), (-7.5, 2.4)))


def draw_line(p, fg, accent):
    p.setPen(_line(fg, 2))
    p.drawLine(QPointF(5.5, 18.5), QPointF(18.5, 5.5))
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    p.drawEllipse(QPointF(5.5, 18.5), 2.6, 2.6)
    p.drawEllipse(QPointF(18.5, 5.5), 2.6, 2.6)


def draw_arrow(p, fg, accent):
    p.setPen(_line(accent, 2.2))
    p.drawLine(QPointF(5, 19), QPointF(18, 6))
    p.setPen(_line(fg, 2.2))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(_poly((10, 6), (18, 6), (18, 14)))


def draw_rect(p, fg, accent):
    p.setPen(_line(fg, 1.9))
    p.setBrush(_alpha(accent, 70))
    p.drawRoundedRect(QRectF(4, 6, 16, 12), 2.5, 2.5)


def draw_ellipse(p, fg, accent):
    p.setPen(_line(fg, 1.9))
    p.setBrush(_alpha(accent, 70))
    p.drawEllipse(QRectF(3.5, 5.5, 17, 13))


def draw_eraser(p, fg, accent):
    p.setPen(_line(_alpha(fg, 110), 1.6))
    p.drawLine(QPointF(9, 20.5), QPointF(20, 20.5))
    p.translate(12, 12)
    p.rotate(-45)
    p.setPen(_line(fg, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-8, -4.2, 16, 8.4), 2, 2)
    p.setBrush(_alpha(fg, 170))
    path = QPainterPath()
    path.addRoundedRect(QRectF(-8, -4.2, 7, 8.4), 2, 2)
    p.drawPath(path)


def draw_undo(p, fg, accent):
    p.setPen(_line(fg, 2))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(5.5, 9))
    path.lineTo(14, 9)
    path.cubicTo(20.5, 9, 20.5, 19, 14, 19)
    path.lineTo(9, 19)
    p.drawPath(path)
    p.drawPolyline(_poly((9, 5.2), (5.2, 9), (9, 12.8)))


def draw_trash(p, fg, accent):
    p.setPen(_line(fg, 1.8))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
    p.drawPolyline(_poly((9.5, 7), (9.5, 4.3), (14.5, 4.3), (14.5, 7)))
    p.drawPolygon(_poly((6.3, 7), (7.4, 20), (16.6, 20), (17.7, 7)))
    p.drawLine(QPointF(10.3, 10.5), QPointF(10.3, 16.5))
    p.drawLine(QPointF(13.7, 10.5), QPointF(13.7, 16.5))


def draw_power(p, fg, accent):
    p.setPen(_line(fg, 2))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(5, 6, 14, 14), 125 * 16, 290 * 16)
    p.drawLine(QPointF(12, 3.5), QPointF(12, 11))


def draw_hide(p, fg, accent):
    p.setPen(_line(fg, 2))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(12, 4), QPointF(12, 15))
    p.drawPolyline(_poly((7.5, 10.5), (12, 15), (16.5, 10.5)))
    p.drawLine(QPointF(5, 19.5), QPointF(19, 19.5))


def draw_app_icon(p, fg, accent):
    """Gradient tile with a white pen, matching the draw-mode button."""
    tile = QLinearGradient(0, 0, 24, 24)
    tile.setColorAt(0, QColor("#7b5cff"))
    tile.setColorAt(1, QColor("#2f8bff"))
    p.setPen(Qt.NoPen)
    p.setBrush(tile)
    p.drawRoundedRect(QRectF(1, 1, 22, 22), 5.5, 5.5)
    p.translate(12, 12)
    p.scale(0.75, 0.75)
    p.translate(-12, -12)
    white = QColor("#ffffff")
    draw_pen(p, white, white)


def _pixmap(draw, fg, accent, size=ICON_SIZE) -> QPixmap:
    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    draw(p, QColor(fg), QColor(accent))
    p.end()
    return pm


def make_icon(draw, accent=None, size=ICON_SIZE) -> QIcon:
    """Icon with a dimmer 'off' look and a bright 'on' (checked) look."""
    icon = QIcon()
    icon.addPixmap(_pixmap(draw, ICON_FG, accent or ICON_FG, size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap(draw, ICON_FG_ON, accent or ICON_FG_ON, size), QIcon.Normal, QIcon.On)
    return icon


def make_size_icon(diameter, accent) -> QIcon:
    def draw(p, fg, ac):
        p.setPen(_line(_alpha(QColor("#ffffff"), 60), 1))
        p.setBrush(ac)
        p.drawEllipse(QPointF(12, 12), diameter / 2, diameter / 2)
    return make_icon(draw, accent)


def make_swatch_icon(hex_color, size=26) -> QIcon:
    def draw(p, ring):
        color = QColor(hex_color)
        if ring:
            p.setPen(_line(QColor("#ffffff"), 1.8))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(12, 12), 10.6, 10.6)
        radius = 7.6 if ring else 9
        sheen = QRadialGradient(QPointF(9.5, 9), radius * 1.6)
        sheen.setColorAt(0, color.lighter(135))
        sheen.setColorAt(1, color.darker(110))
        p.setPen(_line(_alpha(QColor("#ffffff"), 55), 1))
        p.setBrush(sheen)
        p.drawEllipse(QPointF(12, 12), radius, radius)

    icon = QIcon()
    for ring, state in ((False, QIcon.Off), (True, QIcon.On)):
        icon.addPixmap(_pixmap(lambda p, fg, ac, r=ring: draw(p, r), None, None, size),
                       QIcon.Normal, state)
    return icon


def grip_pixmap() -> QPixmap:
    def draw(p, fg, accent):
        p.setPen(Qt.NoPen)
        p.setBrush(_alpha(fg, 130))
        for x in (6, 12, 18):
            for y in (9, 15):
                p.drawEllipse(QPointF(x, y), 1.5, 1.5)
    return _pixmap(draw, ICON_FG, ICON_FG, 24)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_pixmap(draw_app_icon, "#ffffff", "#ffffff", size))
    return icon


TOOL_ICONS = {
    PEN: (draw_pen, "Pen"),
    HIGHLIGHTER: (draw_highlighter, "Highlighter"),
    LINE: (draw_line, "Line"),
    ARROW: (draw_arrow, "Arrow"),
    RECT: (draw_rect, "Rectangle"),
    ELLIPSE: (draw_ellipse, "Ellipse"),
    ERASER: (draw_eraser, "Eraser (removes whole strokes)"),
}


class Overlay(QWidget):
    """Full-screen transparent canvas that holds and renders all strokes."""

    drawing_changed = Signal(bool)

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())

        self.strokes: list[Stroke] = []
        self.history: list[list[Stroke]] = []  # snapshots of `strokes` for undo
        self.current: Stroke | None = None
        self.erasing_snapshot_taken = False

        self.drawing = False
        self.tool = PEN
        self.color = QColor(COLORS[0])
        self.width = WIDTHS["M"]
        self._update_cursor()

    # --- mode -------------------------------------------------------------

    def set_drawing(self, enabled: bool):
        if enabled == self.drawing:
            return
        self.drawing = enabled
        self.current = None
        self._set_click_through(not enabled)
        self.update()
        self.drawing_changed.emit(enabled)

    def set_tool(self, tool):
        self.tool = tool
        self._update_cursor()

    def set_color(self, color: QColor):
        self.color = QColor(color)
        self._update_cursor()

    def set_width(self, width):
        self.width = width
        self._update_cursor()

    def _update_cursor(self):
        """Show a ring the size of the brush, or a crosshair for shapes."""
        if self.tool not in FREEHAND + (ERASER,):
            self.setCursor(Qt.CrossCursor)
            return
        if self.tool == ERASER:
            diameter, ring = ERASER_RADIUS * 2, QColor("#ffffff")
        else:
            diameter = self.width * (HIGHLIGHTER_SCALE if self.tool == HIGHLIGHTER else 1)
            ring = QColor(self.color)
        diameter = max(diameter, 6)
        size = int(diameter + 6)
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        center = QPointF(size / 2, size / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 150), 3))  # dark halo keeps it visible on light apps
        p.drawEllipse(center, diameter / 2, diameter / 2)
        p.setPen(QPen(ring, 1.5))
        p.drawEllipse(center, diameter / 2, diameter / 2)
        p.end()
        self.setCursor(QCursor(pm, size // 2, size // 2))

    def _set_click_through(self, on: bool):
        if sys.platform == "win32":
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED
            style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        else:
            self.setWindowFlag(Qt.WindowTransparentForInput, on)
            self.show()

    def showEvent(self, event):
        super().showEvent(event)
        self._set_click_through(not self.drawing)

    # --- editing ----------------------------------------------------------

    def _snapshot(self):
        self.history.append(list(self.strokes))

    def undo(self):
        if self.history:
            self.strokes = self.history.pop()
            self.update()

    def clear(self):
        if self.strokes:
            self._snapshot()
            self.strokes = []
            self.update()

    def _erase_at(self, point: QPointF):
        hits = [s for s in self.strokes if s.hit(point)]
        if not hits:
            return
        if not self.erasing_snapshot_taken:  # one undo step per eraser drag
            self._snapshot()
            self.erasing_snapshot_taken = True
        self.strokes = [s for s in self.strokes if s not in hits]
        self.update()

    # --- events -----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.drawing:
            # Fully transparent pixels let clicks fall through on Windows, so
            # draw mode needs a barely-visible fill to catch the mouse.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        for stroke in self.strokes:
            stroke.draw(painter)
        if self.current:
            self.current.draw(painter)

    def mousePressEvent(self, event):
        if not self.drawing or event.button() != Qt.LeftButton:
            return
        pos = event.position()
        if self.tool == ERASER:
            self.erasing_snapshot_taken = False
            self._erase_at(pos)
            return
        points = [pos] if self.tool in FREEHAND else [pos, pos]
        self.current = Stroke(self.tool, QColor(self.color), self.width, points)
        self.update()

    def mouseMoveEvent(self, event):
        if not self.drawing or not (event.buttons() & Qt.LeftButton):
            return
        pos = event.position()
        if self.tool == ERASER:
            self._erase_at(pos)
        elif self.current:
            if self.tool in FREEHAND:
                self.current.points.append(pos)
            else:
                self.current.points[-1] = pos
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self.current:
            return
        self.current.freeze()
        self._snapshot()
        self.strokes.append(self.current)
        self.current = None
        self.update()


APP_STYLE = """
QToolTip {
    background: #24262e;
    color: #eceef4;
    border: 1px solid #3c3f4a;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}
"""

TOOLBAR_STYLE = """
#panel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2c2e38, stop:1 #17181e);
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 16px;
}
QPushButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    min-width: 36px; max-width: 36px;
    min-height: 34px; max-height: 34px;
}
QPushButton:hover { background: rgba(255, 255, 255, 18); }
QPushButton:pressed { background: rgba(255, 255, 255, 34); }
QPushButton:checked {
    background: rgba(255, 255, 255, 26);
    border: 1px solid rgba(120, 140, 255, 220);
}
QPushButton#toggle {
    min-height: 38px; max-height: 38px;
    background: rgba(255, 255, 255, 14);
}
QPushButton#toggle:checked {
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #7b5cff, stop:1 #2f8bff);
}
QPushButton#swatch {
    min-width: 30px; max-width: 30px;
    min-height: 28px; max-height: 28px;
    border: none;
}
QPushButton#swatch:hover, QPushButton#swatch:checked { background: transparent; }
QPushButton#danger:hover { background: rgba(255, 69, 58, 70); }
QFrame#sep {
    background: rgba(255, 255, 255, 20);
    min-height: 1px; max-height: 1px;
    margin: 3px 6px;
}
"""


class Toolbar(QWidget):
    """Draggable vertical palette that drives the overlay."""

    SHADOW_MARGIN = 16

    def __init__(self, overlay: Overlay):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(TOOLBAR_STYLE)
        self.overlay = overlay
        self._drag_offset = None

        panel = QFrame(self)
        panel.setObjectName("panel")
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        panel.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self)
        m = self.SHADOW_MARGIN
        outer.setContentsMargins(m, m - 6, m, m + 6)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 4, 7, 8)
        layout.setSpacing(3)

        grip = QLabel()
        grip.setPixmap(grip_pixmap())
        grip.setAlignment(Qt.AlignCenter)
        grip.setToolTip("Drag to move")
        grip.setCursor(Qt.SizeAllCursor)
        layout.addWidget(grip)

        self.toggle = self._button("", checkable=True, name="toggle")
        self.toggle.toggled.connect(overlay.set_drawing)
        overlay.drawing_changed.connect(self._on_drawing_changed)
        layout.addWidget(self.toggle)
        layout.addWidget(self._separator())

        self.tools = QButtonGroup(self)
        self.tool_buttons = {}
        for tool, (_, tip) in TOOL_ICONS.items():
            btn = self._button(tip, checkable=True)
            btn.setChecked(tool == overlay.tool)
            btn.clicked.connect(lambda _=False, t=tool: self._pick_tool(t))
            self.tools.addButton(btn)
            self.tool_buttons[tool] = btn
            layout.addWidget(btn)
        layout.addWidget(self._separator())

        self.colors = QButtonGroup(self)
        for hex_color in COLORS:
            btn = self._button(hex_color, checkable=True, name="swatch")
            btn.setIcon(make_swatch_icon(hex_color))
            btn.setIconSize(QSize(26, 26))
            btn.setChecked(hex_color == COLORS[0])
            btn.clicked.connect(lambda _=False, c=hex_color: self._pick_color(c))
            self.colors.addButton(btn)
            layout.addWidget(btn, alignment=Qt.AlignHCenter)
        layout.addWidget(self._separator())

        self.sizes = QButtonGroup(self)
        self.size_buttons = {}
        for label, width in WIDTHS.items():
            btn = self._button(f"Size {label}", checkable=True)
            btn.setChecked(width == overlay.width)
            btn.clicked.connect(lambda _=False, w=width: self.overlay.set_width(w))
            self.sizes.addButton(btn)
            self.size_buttons[width] = btn
            layout.addWidget(btn)
        layout.addWidget(self._separator())

        for draw, tip, slot, name in [
            (draw_undo, "Undo", overlay.undo, ""),
            (draw_trash, "Clear all", overlay.clear, "danger"),
            (draw_hide, "Hide to tray (drawings stay)", self.hide_to_tray, ""),
            (draw_power, "Quit", QApplication.quit, "danger"),
        ]:
            btn = self._button(tip, name=name)
            btn.setIcon(make_icon(draw))
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        self._refresh_icons()
        self._on_drawing_changed(overlay.drawing)

        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.left() + 8, screen.center().y() - self.height() // 2)

    def show_toolbar(self):
        # Pull the toolbar back on screen if a monitor change left it outside.
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if not screen.intersects(self.frameGeometry()):
            self.move(screen.left() + 8, screen.center().y() - self.height() // 2)
        self.show()
        self.raise_()

    def hide_to_tray(self):
        # Without the toolbar there'd be no way to leave draw mode, so leave it first.
        self.overlay.set_drawing(False)
        self.hide()

    def toggle_visible(self):
        if self.isVisible():
            self.hide_to_tray()
        else:
            self.show_toolbar()

    def _button(self, tip, checkable=False, name="") -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        if name:
            btn.setObjectName(name)
        return btn

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("sep")
        return sep

    def _refresh_icons(self):
        """Tool and size icons are tinted with the current ink color."""
        accent = self.overlay.color
        for tool, btn in self.tool_buttons.items():
            btn.setIcon(make_icon(TOOL_ICONS[tool][0], accent))
        for width, btn in self.size_buttons.items():
            btn.setIcon(make_size_icon(min(4 + width, 16), accent))

    def _pick_tool(self, tool):
        self.overlay.set_tool(tool)
        self.overlay.set_drawing(True)  # picking a tool implies you want to draw

    def _pick_color(self, hex_color):
        self.overlay.set_color(QColor(hex_color))
        self._refresh_icons()
        if self.overlay.tool == ERASER:
            self.overlay.set_tool(PEN)
            self.tool_buttons[PEN].setChecked(True)

    def _on_drawing_changed(self, enabled):
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)
        if enabled:
            self.toggle.setIcon(make_icon(draw_pen, ICON_FG_ON))
            self.toggle.setToolTip("Drawing - click to use your apps again")
        else:
            self.toggle.setIcon(make_icon(draw_cursor))
            self.toggle.setToolTip("Clicks pass through - click to start drawing")
        self.raise_()  # keep the toolbar above the overlay

    # Dragging: the grip label and panel margins don't consume mouse events,
    # so presses there reach this window.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


def launch_command() -> str:
    """Command line that starts this app, for the 'Start with Windows' entry."""
    if getattr(sys, "frozen", False):  # packaged ScreenDraw.exe
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class Tray(QSystemTrayIcon):
    """Tray icon: left-click shows/hides the toolbar, right-click opens the menu."""

    def __init__(self, overlay: Overlay, toolbar: Toolbar):
        super().__init__(app_icon())
        self.toolbar = toolbar
        self.setToolTip(APP_NAME)

        self.menu = QMenu()
        self.show_action = self.menu.addAction("Show toolbar", toolbar.toggle_visible)
        self.draw_action = self.menu.addAction("Draw mode")
        self.draw_action.setCheckable(True)
        self.draw_action.toggled.connect(self._set_drawing)
        overlay.drawing_changed.connect(self._on_drawing_changed)
        self.menu.addAction("Clear all", overlay.clear)
        self.menu.addSeparator()
        if sys.platform == "win32":
            startup = self.menu.addAction("Start with Windows")
            startup.setCheckable(True)
            startup.setChecked(startup_enabled())
            startup.toggled.connect(set_startup)
            self.menu.addSeparator()
        self.menu.addAction("Quit", QApplication.quit)
        self.menu.aboutToShow.connect(self._sync_labels)
        self.setContextMenu(self.menu)

        self.activated.connect(self._on_activated)

    def _set_drawing(self, enabled):
        if enabled:
            self.toolbar.show_toolbar()  # drawing needs the toolbar to get back out
        self.toolbar.overlay.set_drawing(enabled)

    def _on_drawing_changed(self, enabled):
        self.draw_action.blockSignals(True)
        self.draw_action.setChecked(enabled)
        self.draw_action.blockSignals(False)

    def _sync_labels(self):
        self.show_action.setText("Hide toolbar" if self.toolbar.isVisible() else "Show toolbar")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toolbar.toggle_visible()


def main():
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(APP_STYLE)
    app.setQuitOnLastWindowClosed(False)  # hiding the toolbar must not quit

    # Already running? Ask that copy to show its toolbar and get out of the way.
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        return

    overlay = Overlay()
    toolbar = Toolbar(overlay)
    tray = Tray(overlay, toolbar)

    QLocalServer.removeServer(INSTANCE_KEY)
    server = QLocalServer()
    server.newConnection.connect(lambda: (server.nextPendingConnection(), toolbar.show_toolbar()))
    server.listen(INSTANCE_KEY)

    # Keep the startup entry pointing at wherever this copy now lives.
    if sys.platform == "win32" and startup_enabled():
        set_startup(True)

    overlay.show()
    toolbar.show_toolbar()
    tray.show()
    app.aboutToQuit.connect(tray.hide)  # don't leave a ghost icon in the tray
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
