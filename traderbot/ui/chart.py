"""Live candlestick chart.

Bars are drawn at their index, not their time, so nights and weekends leave
no gaps; the bottom axis turns indexes back into dates. Panes (volume, RSI,
MACD) share the price pane's x axis, and every pane rescales its y axis to
the bars in view whenever the view moves.
"""

import datetime as dt

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import indicators as ind
from . import theme

pg.setConfigOptions(antialias=True, background=theme.BG, foreground=theme.MUTED)

OVERLAYS = {"ema20": "EMA 20", "ema50": "EMA 50", "sma200": "SMA 200", "bb": "Bollinger (20, 2)"}
PANES = {"volume": "Hacim", "rsi": "RSI (14)", "macd": "MACD (12, 26, 9)"}
INTERVAL_NAMES = {"1m": "1dk", "2m": "2dk", "5m": "5dk", "15m": "15dk", "30m": "30dk",
                  "60m": "1sa", "1h": "1sa", "90m": "90dk", "1d": "Günlük", "1wk": "Haftalık",
                  "1mo": "Aylık"}
INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "1h", "90m"}


class CandleItem(pg.GraphicsObject):
    """Candles drawn once into a QPicture; dataBounds lets panes fit y to the view."""

    def __init__(self):
        super().__init__()
        self._pic = QtGui.QPicture()
        self._o = self._h = self._l = self._c = np.zeros(0)

    def set_data(self, o, h, l, c):
        self._o, self._h, self._l, self._c = o, h, l, c
        pic = QtGui.QPicture()
        p = QtGui.QPainter(pic)
        up_pen, dn_pen = pg.mkPen(theme.UP, width=1), pg.mkPen(theme.DOWN, width=1)
        up_br, dn_br = pg.mkBrush(theme.UP), pg.mkBrush(theme.DOWN)
        w = 0.34
        for i in range(len(c)):
            up = c[i] >= o[i]
            p.setPen(up_pen if up else dn_pen)
            p.drawLine(QtCore.QPointF(i, l[i]), QtCore.QPointF(i, h[i]))
            p.setBrush(up_br if up else dn_br)
            top, bottom = max(o[i], c[i]), min(o[i], c[i])
            if top - bottom <= 0:
                p.drawLine(QtCore.QPointF(i - w, c[i]), QtCore.QPointF(i + w, c[i]))
            else:
                p.drawRect(QtCore.QRectF(i - w, bottom, 2 * w, top - bottom))
        p.end()
        self.prepareGeometryChange()
        self._pic = pic
        self.update()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self._pic)

    def boundingRect(self):
        if not len(self._c):
            return QtCore.QRectF()
        lo, hi = float(np.nanmin(self._l)), float(np.nanmax(self._h))
        return QtCore.QRectF(-1, lo, len(self._c) + 1, hi - lo)

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        if not len(self._c):
            return None, None
        if ax == 0:
            return 0, len(self._c) - 1
        a, b = 0, len(self._c)
        if orthoRange is not None:
            a = max(0, int(np.floor(orthoRange[0])))
            b = min(len(self._c), int(np.ceil(orthoRange[1])) + 1)
        if b <= a:
            return None, None
        return float(np.nanmin(self._l[a:b])), float(np.nanmax(self._h[a:b]))


class IndexAxis(pg.AxisItem):
    """Bottom axis: bar index -> local exchange time."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.times = []
        self.intraday = True

    def tickStrings(self, values, scale, spacing):
        out = []
        n = len(self.times)
        for v in values:
            i = int(round(v))
            if not n or i < 0 or i >= n:
                out.append("")
                continue
            t = self.times[i]
            if self.intraday:
                prev = self.times[i - 1] if i > 0 else None
                new_day = prev is None or prev.date() != t.date()
                out.append(t.strftime("%d.%m %H:%M" if new_day and spacing >= 1 else "%H:%M"))
            else:
                out.append(t.strftime("%d.%m.%y"))
        return out


class HumanAxis(pg.AxisItem):
    """Right axis for volume: 150M instead of 1.5e+08."""

    def tickStrings(self, values, scale, spacing):
        return [_human(v) if v >= 0 else "" for v in values]


class ChartWidget(QtWidgets.QWidget):
    crosshair_moved = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = None
        self.meta = {}
        self.overlays = {"ema20", "ema50", "bb"}
        self.panes = {"volume", "rsi", "macd"}
        self.markers = []
        self.position_price = None
        self.follow = True
        self._first_view = True

        self.info = QtWidgets.QLabel()
        self.info.setTextFormat(QtCore.Qt.RichText)
        self.info.setStyleSheet("padding: 4px 6px; font-family: Consolas, 'DejaVu Sans Mono', monospace;")
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.ci.setSpacing(0)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.info)
        lay.addWidget(self.glw, 1)
        self._build()

    # ------------------------------------------------------------ layout

    def _new_plot(self, row, height, human=False):
        axes = {"bottom": IndexAxis(orientation="bottom")}
        if human:
            axes["right"] = HumanAxis(orientation="right")
        p = self.glw.addPlot(row=row, col=0, axisItems=axes)
        p.showGrid(x=True, y=True, alpha=0.12)
        p.setMenuEnabled(False)
        p.hideButtons()
        p.getAxis("right").setWidth(64)
        p.showAxis("right")
        p.hideAxis("left")
        p.setMouseEnabled(x=True, y=False)
        self.glw.ci.layout.setRowStretchFactor(row, height)
        return p

    def _build(self):
        self.glw.clear()
        self.price = self._new_plot(0, 6)
        self.candles = CandleItem()
        self.price.addItem(self.candles)
        self.overlay_items = {}
        for key, color in (("ema20", theme.EMA_FAST), ("ema50", theme.EMA_SLOW),
                           ("sma200", theme.SMA_LONG)):
            it = self.price.plot(pen=pg.mkPen(color, width=1.3))
            self.overlay_items[key] = [it]
        bb_up = self.price.plot(pen=pg.mkPen(theme.BB, width=1))
        bb_lo = self.price.plot(pen=pg.mkPen(theme.BB, width=1))
        bb_fill = pg.FillBetweenItem(bb_up, bb_lo, brush=pg.mkBrush(92, 107, 192, 28))
        self.price.addItem(bb_fill)
        self.overlay_items["bb"] = [bb_up, bb_lo, bb_fill]
        self.last_line = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen(theme.ACCENT, width=1, style=QtCore.Qt.DashLine))
        self.last_label = pg.InfLineLabel(self.last_line, text="", position=0.98,
                                          anchors=[(1, 1), (1, 1)], color=theme.ACCENT)
        self.price.addItem(self.last_line, ignoreBounds=True)
        self.pos_line = pg.InfiniteLine(angle=0, movable=False,
                                        pen=pg.mkPen(theme.WARN, width=1, style=QtCore.Qt.DotLine))
        pg.InfLineLabel(self.pos_line, text="ortalama maliyet", position=0.05, color=theme.WARN)
        self.price.addItem(self.pos_line, ignoreBounds=True)
        self.buys = pg.ScatterPlotItem(symbol="t1", size=13, brush=pg.mkBrush(theme.UP),
                                       pen=pg.mkPen("#0b3d36"))
        self.sells = pg.ScatterPlotItem(symbol="t", size=13, brush=pg.mkBrush(theme.DOWN),
                                        pen=pg.mkPen("#4a1414"))
        self.price.addItem(self.buys)
        self.price.addItem(self.sells)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.MUTED, width=0.6))
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(theme.MUTED, width=0.6))
        self.price.addItem(self.vline, ignoreBounds=True)
        self.price.addItem(self.hline, ignoreBounds=True)

        self.sub = {}
        row = 1
        if "volume" in self.panes:
            p = self._new_plot(row, 1, human=True)
            item = pg.BarGraphItem(x=[], height=[], width=0.7, brush=theme.MUTED)
            p.addItem(item)
            self.sub["volume"] = (p, {"bars": item})
            row += 1
        if "rsi" in self.panes:
            p = self._new_plot(row, 1.4)
            line = p.plot(pen=pg.mkPen("#c792ea", width=1.2))
            for lvl, alpha in ((70, 120), (30, 120), (50, 50)):
                p.addItem(pg.InfiniteLine(angle=0, pos=lvl, movable=False,
                                          pen=pg.mkPen(139, 148, 158, alpha, style=QtCore.Qt.DashLine)))
            p.setYRange(0, 100, padding=0.02)
            self.sub["rsi"] = (p, {"line": line})
            row += 1
        if "macd" in self.panes:
            p = self._new_plot(row, 1.4)
            hist = pg.BarGraphItem(x=[], height=[], width=0.7, brush=theme.MUTED)
            p.addItem(hist)
            line = p.plot(pen=pg.mkPen(theme.MACD_LINE, width=1.2))
            sig = p.plot(pen=pg.mkPen(theme.MACD_SIGNAL, width=1.2))
            self.sub["macd"] = (p, {"hist": hist, "line": line, "signal": sig})
            row += 1
        plots = [self.price] + [p for p, _ in self.sub.values()]
        for p in plots[1:]:
            p.setXLink(self.price)
        # only the bottom pane shows dates
        for p in plots[:-1]:
            p.getAxis("bottom").setStyle(showValues=False)
            p.getAxis("bottom").setHeight(4)
        self.price.sigXRangeChanged.connect(self._fit_y)
        self._mouse = pg.SignalProxy(self.glw.scene().sigMouseMoved, rateLimit=60,
                                     slot=self._on_mouse)
        if self.bars is not None:
            self._draw()

    def set_indicators(self, overlays, panes):
        rebuild = set(panes) != self.panes
        self.overlays, self.panes = set(overlays), set(panes)
        if rebuild:
            view = self.price.viewRange()[0]
            self._build()
            self.price.setXRange(*view, padding=0)
        else:
            self._draw()

    # ------------------------------------------------------------ data

    def set_bars(self, bars, meta=None):
        """Replace everything (new symbol or interval)."""
        self.bars = bars
        self.meta = meta or {}
        self._first_view = True
        self.follow = True
        self._draw()

    def update_bars(self, bars, meta=None):
        """Live refresh: keep the user's view unless they were at the right edge."""
        if self.bars is None or bars is None or self.bars.symbol != bars.symbol \
                or self.bars.interval != bars.interval:
            return self.set_bars(bars, meta)
        x0, x1 = self.price.viewRange()[0]
        n_old = len(self.bars)
        self.follow = x1 >= n_old - 2
        self.bars = bars
        if meta:
            self.meta = meta
        self._draw()
        if self.follow:
            shift = len(bars) - n_old
            if shift:
                self.price.setXRange(x0 + shift, x1 + shift, padding=0)

    def set_markers(self, trades):
        """trades: [{"time": unix seconds, "side": "buy"/"sell", "price": float}]"""
        self.markers = list(trades or [])
        self._draw_markers()

    def set_position_price(self, price):
        self.position_price = price
        self.pos_line.setVisible(bool(price))
        if price:
            self.pos_line.setPos(price)

    # ------------------------------------------------------------ drawing

    def _draw(self):
        b = self.bars
        if b is None or not len(b):
            self.candles.set_data(np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0))
            self.info.setText("<span style='color:%s'>Veri yok</span>" % theme.MUTED)
            return
        n = len(b)
        x = np.arange(n, dtype=float)
        self.candles.set_data(b.o, b.h, b.l, b.c)
        intraday = b.interval in INTRADAY
        times = [b.local_datetime(i) for i in range(n)]
        for p in [self.price] + [p for p, _ in self.sub.values()]:
            ax = p.getAxis("bottom")
            ax.times, ax.intraday = times, intraday
            ax.picture = None
            ax.update()
        c = b.c
        series = {"ema20": ind.ema(c, 20), "ema50": ind.ema(c, 50), "sma200": ind.sma(c, 200)}
        for key, ys in series.items():
            item = self.overlay_items[key][0]
            item.setData(x, ys, connect="finite")
            item.setVisible(key in self.overlays)
        mid, up, lo = ind.bollinger(c, 20, 2.0)
        ok = np.isfinite(up)
        self.overlay_items["bb"][0].setData(x[ok], up[ok])
        self.overlay_items["bb"][1].setData(x[ok], lo[ok])
        for it in self.overlay_items["bb"]:
            it.setVisible("bb" in self.overlays)
        up_mask = c >= b.o
        if "volume" in self.sub:
            brushes = [pg.mkBrush(38, 166, 154, 140) if u else pg.mkBrush(239, 83, 80, 140)
                       for u in up_mask]
            self.sub["volume"][1]["bars"].setOpts(x=x, height=b.v, width=0.7, brushes=brushes)
        if "rsi" in self.sub:
            self.sub["rsi"][1]["line"].setData(x, ind.rsi(c, 14), connect="finite")
        if "macd" in self.sub:
            line, sig, hist = ind.macd(c)
            h = np.nan_to_num(hist)
            brushes = [pg.mkBrush(38, 166, 154, 150) if v >= 0 else pg.mkBrush(239, 83, 80, 150)
                       for v in h]
            items = self.sub["macd"][1]
            items["hist"].setOpts(x=x, height=h, width=0.7, brushes=brushes)
            items["line"].setData(x, line, connect="finite")
            items["signal"].setData(x, sig, connect="finite")
        last = float(c[-1])
        self.last_line.setPos(last)
        self.last_line.setPen(pg.mkPen(theme.UP if up_mask[-1] else theme.DOWN, width=1,
                                       style=QtCore.Qt.DashLine))
        self.last_label.setText(_fmt(last))
        self.pos_line.setVisible(bool(self.position_price))
        self._draw_markers()
        if self._first_view:
            self._first_view = False
            span = 160 if intraday else 250
            self.price.setXRange(max(-1, n - span), n + 2, padding=0)
        self._fit_y()
        self._show_info(n - 1)

    def _draw_markers(self):
        b = self.bars
        if b is None or not len(b):
            return
        bx, by, sx, sy = [], [], [], []
        span = (b.t[1] - b.t[0]) if len(b) > 1 else 60
        for m in self.markers:
            i = int(np.searchsorted(b.t, int(m["time"]), side="right")) - 1
            if i < 0 or (i == len(b) - 1 and m["time"] > b.t[-1] + span * 2):
                continue
            if m["side"] == "buy":
                bx.append(i)
                by.append(b.l[i] * 0.998)
            else:
                sx.append(i)
                sy.append(b.h[i] * 1.002)
        self.buys.setData(bx, by)
        self.sells.setData(sx, sy)

    def _fit_y(self, *args):
        b = self.bars
        if b is None or not len(b):
            return
        x0, x1 = self.price.viewRange()[0]
        a = max(0, int(np.floor(x0)))
        z = min(len(b), int(np.ceil(x1)) + 1)
        if z - a < 1:
            return
        lo, hi = float(np.nanmin(b.l[a:z])), float(np.nanmax(b.h[a:z]))
        if "bb" in self.overlays:
            _, up, low = ind.bollinger(b.c, 20, 2.0)
            seg_u, seg_l = up[a:z], low[a:z]
            if np.isfinite(seg_u).any():
                hi = max(hi, float(np.nanmax(seg_u)))
                lo = min(lo, float(np.nanmin(seg_l)))
        pad = (hi - lo) * 0.06 or hi * 0.01 or 1.0
        self.price.setYRange(lo - pad, hi + pad, padding=0)
        if "volume" in self.sub:
            vmax = float(np.nanmax(b.v[a:z])) if z > a else 1.0
            self.sub["volume"][0].setYRange(0, max(vmax, 1.0) * 1.1, padding=0)
        if "macd" in self.sub:
            line, sig, hist = ind.macd(b.c)
            seg = np.concatenate([line[a:z], sig[a:z], hist[a:z]])
            seg = seg[np.isfinite(seg)]
            if len(seg):
                m = max(abs(float(seg.min())), abs(float(seg.max()))) * 1.1 or 1.0
                self.sub["macd"][0].setYRange(-m, m, padding=0)

    # ------------------------------------------------------------ crosshair

    def _on_mouse(self, evt):
        pos = evt[0]
        if self.bars is None or not len(self.bars):
            return
        if not self.price.sceneBoundingRect().contains(pos):
            return
        pt = self.price.vb.mapSceneToView(pos)
        i = int(round(pt.x()))
        i = min(max(i, 0), len(self.bars) - 1)
        self.vline.setPos(i)
        self.hline.setPos(pt.y())
        self._show_info(i, pt.y())

    def _show_info(self, i, cursor=None):
        b = self.bars
        t = b.local_datetime(i)
        prev = b.c[i - 1] if i > 0 else b.o[i]
        chg = (b.c[i] / prev - 1) * 100 if prev else 0.0
        col = theme.color_for(chg)
        name = self.meta.get("longName") or self.meta.get("shortName") or ""
        when = t.strftime("%d.%m.%Y %H:%M" if b.interval in INTRADAY else "%d.%m.%Y")
        parts = [
            "<b>%s</b> <span style='color:%s'>%s · %s</span>" % (
                b.symbol, theme.MUTED, INTERVAL_NAMES.get(b.interval, b.interval), name[:40]),
            "<span style='color:%s'>%s</span>" % (theme.MUTED, when),
            "A <b>%s</b>" % _fmt(b.o[i]), "Y <b>%s</b>" % _fmt(b.h[i]),
            "D <b>%s</b>" % _fmt(b.l[i]),
            "K <b style='color:%s'>%s</b>" % (col, _fmt(b.c[i])),
            "<span style='color:%s'>%+.2f%%</span>" % (col, chg),
            "Hacim %s" % _human(b.v[i]),
        ]
        if cursor is not None:
            parts.append("<span style='color:%s'>imleç %s</span>" % (theme.MUTED, _fmt(cursor)))
        text = " &nbsp; ".join(parts)
        self.info.setText(text)
        self.crosshair_moved.emit(text)

    def grab_png(self, path):
        return self.grab().save(path)


def _fmt(x):
    x = float(x)
    if abs(x) >= 1000:
        return "{:,.2f}".format(x)
    if abs(x) >= 1:
        return "%.2f" % x
    return "%.4f" % x


def _human(v):
    v = float(v or 0)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            return "%.2f%s" % (v / div, suf)
    return "%d" % v
