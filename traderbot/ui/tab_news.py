"""News and Congress tabs: trader-news headlines and 8-Ks, trader-pelosi PTRs."""

import datetime as dt

from PySide6 import QtCore, QtGui, QtWidgets

from .. import services
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async


def _open(url):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


class NewsTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.items = []
        self.tickers = QtWidgets.QLineEdit()
        self.tickers.setPlaceholderText("Semboller: SPY, AAPL, KO (boşsa: izleme listesi + pozisyonlar)")
        self.hours = QtWidgets.QSpinBox()
        self.hours.setRange(1, 24 * 30)
        self.hours.setValue(int(ctx.settings.get("news_hours") or 48))
        self.hours.setSuffix(" saat")
        refresh = theme.button("Yenile", "primary")
        refresh.clicked.connect(self.refresh)
        self.table = _table(["Zaman (UTC)", "Semboller", "Kaynak", "Başlık", "Etiketler"], stretch=3)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.notes = theme.label("", "muted", wrap=True)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.tickers, 1)
        bar.addWidget(theme.label("son"))
        bar.addWidget(self.hours)
        bar.addWidget(refresh)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.notes)
        lay.addWidget(theme.label("Başlıklar ipucudur, kesin bilgi değil: karar vermeden önce haberi "
                                  "açıp okuyun. Çift tıklayınca kaynak açılır. ! = önemli 8-K "
                                  "maddesi (kâr, yönetici değişikliği, iflas…).", "muted", wrap=True))

    def _watch(self):
        text = [t.strip().upper() for t in self.tickers.text().split(",") if t.strip()]
        if text:
            return text
        syms = [s for s in (self.ctx.settings.get("watchlist") or [])
                if "." not in s and "-" not in s and "^" not in s and "=" not in s]
        try:
            syms += [p.symbol for p in self.ctx.broker.positions()]
        except Exception:
            pass
        return list(dict.fromkeys(syms))[:25]

    def refresh(self):
        watch = self._watch()
        ua = self.ctx.settings.get("sec_user_agent") or None
        if ua:
            try:
                ua = services.sec_user_agent(ua)
            except services.ServiceError:
                ua = None
        self.status.emit("Haberler alınıyor: %s" % ", ".join(watch))
        run_async(services.headlines, watch, ua, self.hours.value(), done=self._show,
                  failed=lambda m: self.status.emit("Haberler alınamadı: %s" % m))

    def _show(self, res):
        items, notes = res
        self.items = items
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            when = it["time"].strftime("%d.%m %H:%M") if it.get("time") else "?"
            mark = "! " if it.get("important") else ""
            _set_row(self.table, r, [when, ", ".join(it.get("touches") or [it["ticker"]]),
                                     it.get("source", ""), mark + it["title"],
                                     ", ".join(it.get("tags") or [])],
                     {3: theme.WARN if it.get("important") else None})
        self.notes.setText(" · ".join(notes))
        self.status.emit("%d haber/dosyalama" % len(items))

    def _open_row(self, r, c):
        if 0 <= r < len(self.items) and self.items[r].get("link"):
            _open(self.items[r]["link"])


class CongressTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.rows = []
        self.members = QtWidgets.QLineEdit(", ".join(ctx.settings.get("congress_members") or []))
        self.members.setPlaceholderText("Üye: pelosi, gottheimer (boşsa herkes)")
        self.year = QtWidgets.QSpinBox()
        self.year.setRange(2008, 2100)
        self.year.setValue(dt.date.today().year)
        get = theme.button("Getir", "primary")
        get.clicked.connect(self.refresh)
        read = theme.button("Seçileni oku")
        read.clicked.connect(self.read_selected)
        self.table = _table(["Dosyalama", "Üye", "Bölge", "Belge no", "Bağlantı"], stretch=1)
        self.table.cellDoubleClicked.connect(lambda r, c: _open(self.rows[r]["url"]))
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.members, 1)
        bar.addWidget(theme.label("yıl"))
        bar.addWidget(self.year)
        bar.addWidget(get)
        bar.addWidget(read)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(theme.label(
            "ABD Temsilciler Meclisi üyelerinin STOCK Act gereği yayınladığı işlem bildirimleri (PTR). "
            "İşlemden 30-45 gün sonra açıklanır: hızlı okunur ama içeriden bilgi değildir. Tutarlar "
            "aralıktır. Çift tıklayınca PDF açılır.", "muted", wrap=True))

    def refresh(self):
        members = [m.strip() for m in self.members.text().split(",") if m.strip()]
        self.ctx.settings.set("congress_members", members)
        self.status.emit("Meclis endeksi indiriliyor…")
        run_async(services.congress_filings, self.year.value(), members, done=self._show,
                  failed=lambda m: self.status.emit("Kongre verisi alınamadı: %s" % m))

    def _show(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            _set_row(self.table, r, [row["filed"], row["name"], row["district"], row["doc_id"],
                                     row["url"]])
        self.status.emit("%d bildirim" % len(rows))

    def read_selected(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return
        row = self.rows[r]
        run_async(services.read_ptr, row["doc_id"], row["year"], row["filed"],
                  done=self._show_report,
                  failed=lambda m: QtWidgets.QMessageBox.warning(self, "PTR", m))

    def _show_report(self, res):
        if res.get("text"):
            QtWidgets.QMessageBox.information(self, "PTR", res["text"])
        else:
            _open(services.open_target(res["pdf"]))
