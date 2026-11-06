"""Tarayıcı tab: rank a list of symbols on momentum, closeness to the
52-week high, trend and volatility (see screener.py for the evidence)."""

from PySide6 import QtCore, QtGui, QtWidgets

from .. import screener
from . import theme
from .workers import run_async

COLUMNS = [("symbol", "Sembol", None), ("price", "Fiyat", "price"), ("change", "Gün", "pct"),
           ("mom_12_1", "12-1 ay mom.", "pct"), ("mom_6", "6 ay", "pct"),
           ("from_high", "52h zirveden", "pct"), ("trend", "Trend (200g)", "pct"),
           ("vol", "Oynaklık", "pct0"), ("rsi2", "RSI(2)", "num"),
           ("volume_ratio", "Hacim / ort.", "num"), ("score", "Puan", "num0"),
           ("pullback", "Not", None)]
WATCHLIST = "İzleme listem"
CUSTOM = "Özel liste"


class NumItem(QtWidgets.QTableWidgetItem):
    """Sorts by the number behind the text; empty cells go last."""

    def __lt__(self, other):
        a = self.data(QtCore.Qt.UserRole)
        b = other.data(QtCore.Qt.UserRole)
        if a is None:
            return False
        if b is None:
            return True
        return a < b


def fmt(v, kind):
    if v is None:
        return "—"
    if kind == "pct":
        return ("%+.1f%%" % (100 * v)).replace("+-", "-")
    if kind == "pct0":
        return "%.0f%%" % (100 * v)
    if kind == "price":
        return "%.2f" % v
    if kind == "num0":
        return "%.0f" % v
    return "%.2f" % v


class ScreenerTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)
    open_symbol = QtCore.Signal(str)
    size_symbol = QtCore.Signal(str)
    alert_symbol = QtCore.Signal(str)
    watch_symbol = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.rows = []
        self._busy = False
        cfg = ctx.settings.get("screener") or {}
        self.universe = QtWidgets.QComboBox()
        for name in list(screener.UNIVERSES) + [WATCHLIST, CUSTOM]:
            self.universe.addItem(name)
        self.universe.setCurrentIndex(max(0, self.universe.findText(cfg.get("universe") or "")))
        self.custom = QtWidgets.QLineEdit(cfg.get("custom") or "")
        self.custom.setPlaceholderText("Virgülle semboller: AAPL, MSFT, THYAO.IS")
        self.run_btn = theme.button("Tara", "primary")
        self.run_btn.clicked.connect(self.run)
        self.universe.currentIndexChanged.connect(self._universe_changed)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(theme.label("Liste"))
        bar.addWidget(self.universe)
        bar.addWidget(self.custom, 1)
        bar.addWidget(self.run_btn)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, c: self.open_symbol.emit(self._symbol(r)))
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.info = theme.label("Bir liste seçip Tara'ya basın. Çift tıklama sembolü grafikte açar; "
                                "sağ tık: pozisyon hesapla, alarm kur.", "muted", wrap=True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.info)
        lay.addWidget(theme.label(
            "Ölçüler: 12-1 ay momentumu son ayı atlar (Jegadeesh ve Titman 1993); 52 haftalık "
            "zirveye yakınlık (George ve Hwang 2004); 200 günlük ortalama trendi (Faber 2007); "
            "RSI(2) < 10 ve yukarı trend: Connors'ın geri çekilme alımı (2010 sonrası zayıf). "
            "Puan, iki momentum ölçüsünün sıralamasının ortalamasıdır (0-100). Momentum yıllarca "
            "işe yaradı ama sert dönüşlerde çöker (Daniel ve Moskowitz 2016). Bu tablo bir alım "
            "listesi değil, grafiğe bakmak için bir başlangıçtır.", "muted", wrap=True))
        self._universe_changed()

    def _universe_changed(self, *_):
        self.custom.setEnabled(self.universe.currentText() == CUSTOM)

    def symbols(self):
        name = self.universe.currentText()
        if name == WATCHLIST:
            return list(self.ctx.settings.get("watchlist") or [])
        if name == CUSTOM:
            return [s.strip() for s in self.custom.text().replace(";", ",").split(",") if s.strip()]
        return list(screener.UNIVERSES[name])

    def run(self):
        syms = self.symbols()
        if not syms or self._busy:
            return
        self.ctx.settings.set("screener", {"universe": self.universe.currentText(),
                                           "custom": self.custom.text().strip()})
        self._busy = True
        self.run_btn.setEnabled(False)
        self.info.setText("%d sembol taranıyor…" % len(syms))
        run_async(screener.screen, self.ctx.data, syms, done=self._done, failed=self._failed)

    def _failed(self, msg):
        self._busy = False
        self.run_btn.setEnabled(True)
        self.info.setText("Tarama başarısız: %s" % msg)

    def _done(self, out):
        self._busy = False
        self.run_btn.setEnabled(True)
        rows, failed = out
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (key, _, kind) in enumerate(COLUMNS):
                v = row.get(key)
                if key == "symbol":
                    it = QtWidgets.QTableWidgetItem(v)
                elif key == "pullback":
                    it = QtWidgets.QTableWidgetItem("geri çekilme (RSI2<10)" if v else "")
                    it.setForeground(QtGui.QColor(theme.WARN))
                else:
                    it = NumItem(fmt(v, kind))
                    it.setData(QtCore.Qt.UserRole, v)
                    it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    if kind == "pct" and v is not None:
                        it.setForeground(QtGui.QColor(theme.color_for(v)))
                    if key == "score" and v is not None:
                        it.setForeground(QtGui.QColor(theme.UP if v >= 66 else theme.DOWN
                                                      if v <= 33 else theme.TEXT))
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        score_col = [c[0] for c in COLUMNS].index("score")
        self.table.sortItems(score_col, QtCore.Qt.DescendingOrder)
        msg = "%d sembol tarandı, puana göre sıralı." % len(rows)
        if failed:
            msg += " Alınamayan: %s." % ", ".join(sorted(failed))
        self.info.setText(msg)
        self.status.emit(msg)

    def _symbol(self, r):
        it = self.table.item(r, 0)
        return it.text() if it else ""

    def _menu(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        sym = self._symbol(r)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Grafikte aç", lambda: self.open_symbol.emit(sym))
        menu.addAction("Pozisyon hesapla", lambda: self.size_symbol.emit(sym))
        menu.addAction("Alarm kur", lambda: self.alert_symbol.emit(sym))
        menu.addAction("İzleme listesine ekle", lambda: self.watch_symbol.emit(sym))
        menu.exec(self.table.viewport().mapToGlobal(pos))
