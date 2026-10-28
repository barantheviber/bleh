"""Dark theme: one palette for widgets and charts."""

from PySide6 import QtCore, QtGui, QtWidgets

BG = "#0e1117"
PANEL = "#161b22"
PANEL_2 = "#1c2230"
BORDER = "#2d333b"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#2f81f7"
UP = "#26a69a"
DOWN = "#ef5350"
WARN = "#d29922"
LIVE = "#da3633"

# chart series
EMA_FAST = "#f0b429"
EMA_SLOW = "#8e7cc3"
SMA_LONG = "#4fc3f7"
BB = "#5c6bc0"
MACD_LINE = "#2f81f7"
MACD_SIGNAL = "#f0883e"

QSS = """
QWidget { background: %(BG)s; color: %(TEXT)s; font-size: 10pt; }
QMainWindow::separator { background: %(BORDER)s; width: 1px; height: 1px; }
QToolTip { background: %(PANEL_2)s; color: %(TEXT)s; border: 1px solid %(BORDER)s; }
QTabWidget::pane { border: 1px solid %(BORDER)s; top: -1px; background: %(BG)s; }
QTabBar::tab { background: %(PANEL)s; color: %(MUTED)s; padding: 7px 14px;
               border: 1px solid %(BORDER)s; border-bottom: none; margin-right: 2px; }
QTabBar::tab:selected { background: %(BG)s; color: %(TEXT)s; border-top: 2px solid %(ACCENT)s; }
QTabBar::tab:hover { color: %(TEXT)s; }
QPushButton { background: %(PANEL_2)s; border: 1px solid %(BORDER)s; border-radius: 5px;
              padding: 5px 12px; }
QPushButton:hover { border-color: %(ACCENT)s; }
QPushButton:pressed { background: %(BORDER)s; }
QPushButton:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; color: white; }
QPushButton:disabled { color: %(MUTED)s; }
QPushButton[kind="primary"] { background: %(ACCENT)s; border-color: %(ACCENT)s; color: white; }
QPushButton[kind="danger"] { background: %(DOWN)s; border-color: %(DOWN)s; color: white; }
QPushButton[kind="good"] { background: %(UP)s; border-color: %(UP)s; color: white; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit, QDateEdit, QPlainTextEdit,
QTextBrowser, QListWidget {
    background: %(PANEL)s; border: 1px solid %(BORDER)s; border-radius: 4px; padding: 4px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: %(ACCENT)s; }
QComboBox QAbstractItemView { background: %(PANEL)s; selection-background-color: %(ACCENT)s; }
QTableWidget, QTableView { background: %(PANEL)s; alternate-background-color: %(PANEL_2)s;
    gridline-color: %(BORDER)s; border: 1px solid %(BORDER)s; selection-background-color: #23395d; }
QHeaderView::section { background: %(PANEL_2)s; color: %(MUTED)s; padding: 4px;
    border: none; border-right: 1px solid %(BORDER)s; border-bottom: 1px solid %(BORDER)s; }
QGroupBox { border: 1px solid %(BORDER)s; border-radius: 6px; margin-top: 14px; padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: %(MUTED)s; }
QLabel[role="title"] { font-size: 13pt; font-weight: 600; }
QLabel[role="muted"] { color: %(MUTED)s; }
QLabel[role="big"] { font-size: 16pt; font-weight: 600; }
QLabel[role="banner"] { background: %(LIVE)s; color: white; font-weight: 700; padding: 4px 10px; }
QLabel[role="warn"] { background: #3d2e00; color: %(WARN)s; padding: 6px 10px; border-radius: 4px; }
QStatusBar { background: %(PANEL)s; color: %(MUTED)s; border-top: 1px solid %(BORDER)s; }
QScrollBar:vertical { background: %(BG)s; width: 10px; }
QScrollBar::handle:vertical { background: %(BORDER)s; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: %(BG)s; height: 10px; }
QScrollBar::handle:horizontal { background: %(BORDER)s; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled,
QPushButton[kind="good"]:disabled { background: %(PANEL_2)s; border-color: %(BORDER)s;
    color: %(MUTED)s; }
QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px;
    border: 1px solid #6e7681; background: %(PANEL)s; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator { border-radius: 3px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(ACCENT)s; }
QRadioButton::indicator:checked { border-color: %(ACCENT)s; background: qradialgradient(
    cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 white, stop:0.42 white,
    stop:0.5 %(ACCENT)s, stop:1 %(ACCENT)s); }
QCheckBox::indicator:checked { border-color: %(ACCENT)s; background: %(ACCENT)s;
    image: url(%(CHECK)s); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: %(BORDER)s; }
QMenu { background: %(PANEL)s; border: 1px solid %(BORDER)s; }
QMenu::item:selected { background: %(ACCENT)s; }
QDockWidget::title { background: %(PANEL)s; padding: 5px; }
"""
COLORS = dict(BG=BG, PANEL=PANEL, PANEL_2=PANEL_2, BORDER=BORDER, TEXT=TEXT, MUTED=MUTED,
              ACCENT=ACCENT, UP=UP, DOWN=DOWN, WARN=WARN, LIVE=LIVE)


def _check_image():
    """A white check mark PNG for checked boxes (style sheets need a file)."""
    from .. import paths
    path = paths.path("ui", "check.png")
    pm = QtGui.QPixmap(28, 28)
    pm.fill(QtGui.QColor(0, 0, 0, 0))
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor("white"), 4)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QtCore.QPointF(6, 14.5), QtCore.QPointF(11.5, 20), QtCore.QPointF(22, 8)])
    p.end()
    pm.save(path, "PNG")
    return path.replace("\\", "/")


def apply(app):
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    for role, color in ((QtGui.QPalette.Window, BG), (QtGui.QPalette.Base, PANEL),
                        (QtGui.QPalette.AlternateBase, PANEL_2), (QtGui.QPalette.Text, TEXT),
                        (QtGui.QPalette.WindowText, TEXT), (QtGui.QPalette.Button, PANEL_2),
                        (QtGui.QPalette.ButtonText, TEXT), (QtGui.QPalette.Highlight, ACCENT),
                        (QtGui.QPalette.HighlightedText, "#ffffff"),
                        (QtGui.QPalette.ToolTipBase, PANEL_2), (QtGui.QPalette.ToolTipText, TEXT),
                        (QtGui.QPalette.PlaceholderText, MUTED)):
        pal.setColor(role, QtGui.QColor(color))
    app.setPalette(pal)
    try:
        check = _check_image()
    except Exception:  # a missing check mark must never stop the app
        check = ""
    app.setStyleSheet(QSS % dict(COLORS, CHECK=check))


def color_for(value):
    if value is None:
        return MUTED
    return UP if value > 0 else DOWN if value < 0 else MUTED


def button(text, kind=None, tip=None, checkable=False):
    b = QtWidgets.QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tip:
        b.setToolTip(tip)
    b.setCheckable(checkable)
    return b


def label(text="", role=None, wrap=False):
    lb = QtWidgets.QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb
