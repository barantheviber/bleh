"""13F tab: trader-copycat in a window. Find a fund, read its latest 13F-HR,
see what changed, and turn the top holdings into the bot's target weights."""

from PySide6 import QtCore, QtWidgets

from .. import services
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async

STATUS_TR = {"NEW": "YENİ", "SOLD OUT": "TAMAMEN SATTI", "ADDED": "ARTIRDI",
             "TRIMMED": "AZALTTI", "UNCHANGED": "AYNI"}


class CopycatTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result = None
        self.targets = None

        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText("Yatırımcı veya fon: buffett, ackman, burry, bridgewater, ARK… ya da CIK")
        self.query.returnPressed.connect(self.search)
        find = theme.button("Ara", "primary")
        find.clicked.connect(self.search)
        self.hits = QtWidgets.QListWidget()
        self.hits.itemDoubleClicked.connect(lambda *_: self.load())
        load = theme.button("Portföyü getir")
        load.clicked.connect(self.load)
        diff = theme.button("Çeyrek değişimi")
        diff.clicked.connect(self.diff)
        self.top = QtWidgets.QSpinBox()
        self.top.setRange(1, 100)
        self.top.setValue(int((ctx.settings.get("copycat") or {}).get("top") or 10))
        self.min_pct = QtWidgets.QDoubleSpinBox()
        self.min_pct.setRange(0, 50)
        self.min_pct.setSuffix(" %")
        self.exclude = QtWidgets.QLineEdit()
        self.exclude.setPlaceholderText("Hariç tut: BAC, KO")
        make = theme.button("Hedef ağırlıkları hesapla")
        make.clicked.connect(self.make_targets)
        self.apply_btn = theme.button("Bota uygula", "good",
                                      tip="Bot bu ağırlıkları sabit hedef olarak kullanır")
        self.apply_btn.clicked.connect(self.apply_to_bot)
        self.apply_btn.setEnabled(False)

        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(find)
        ll.addLayout(row)
        ll.addWidget(self.hits, 1)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(load)
        row2.addWidget(diff)
        ll.addLayout(row2)
        box = QtWidgets.QGroupBox("Kopyalama (trader-copycat)")
        f = QtWidgets.QFormLayout(box)
        f.addRow("İlk N pozisyon", self.top)
        f.addRow("En az ağırlık", self.min_pct)
        f.addRow("Hariç", self.exclude)
        f.addRow(make)
        f.addRow(self.apply_btn)
        ll.addWidget(box)
        ll.addWidget(theme.label(
            "13F, çeyrek sonunun fotoğrafıdır ve 45 güne kadar gecikmeyle yayınlanır. Yalnızca ABD "
            "hisselerindeki uzun pozisyonları gösterir; fonun bugün ne tuttuğunu değil.", "muted", wrap=True))

        self.meta = theme.label("", wrap=True)
        self.meta.setTextFormat(QtCore.Qt.RichText)
        self.table = _table(["#", "Sembol", "Şirket", "13F payı", "Değer", "Adet", "Not"], stretch=2)
        self.diff_table = _table(["Durum", "Sembol", "Şirket", "Önce", "Sonra", "Değişim %"], stretch=2)
        self.weights = _table(["Sembol", "Şirket", "Kopya ağırlığı", "13F payı"], stretch=1)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.table, "Portföy")
        tabs.addTab(self.diff_table, "Çeyrek değişimi")
        tabs.addTab(self.weights, "Kopya hedefi")
        self.tabs = tabs
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.meta)
        rl.addWidget(tabs, 1)
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 900])
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(split)
        self.query.setText("buffett")
        QtCore.QTimer.singleShot(0, self.search)

    def _ua(self, required=True):
        ua = self.ctx.settings.get("sec_user_agent") or ""
        if not required:
            return ua or None
        return services.sec_user_agent(ua)

    def search(self):
        q = self.query.text().strip()
        if not q:
            return
        run_async(services.find_filers, q, self._ua(required=False), done=self._show_hits,
                  failed=lambda m: self.status.emit("Arama başarısız: %s" % m))

    def _show_hits(self, hits):
        self.hits.clear()
        for h in hits:
            extra = h.get("person") or ""
            it = QtWidgets.QListWidgetItem("%s  %s%s%s" % (
                h["cik"], h["name"], "  (%s)" % extra if extra else "",
                "  [%s]" % h["status"] if h.get("status") else ""))
            it.setData(QtCore.Qt.UserRole, h["cik"])
            self.hits.addItem(it)
        if hits:
            self.hits.setCurrentRow(0)
        if not self.ctx.settings.get("sec_user_agent"):
            self.status.emit("Yalnız hazır listede arandı; tüm SEC için Ayarlar'a SEC kimliği girin")

    def _cik(self):
        it = self.hits.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def load(self):
        cik = self._cik()
        if not cik:
            return
        try:
            ua = self._ua()
        except services.ServiceError as exc:
            QtWidgets.QMessageBox.information(self, "SEC kimliği", str(exc))
            return
        self.status.emit("13F indiriliyor (SEC EDGAR)…")
        run_async(services.holdings, cik, ua, done=self._show_holdings,
                  failed=lambda m: QtWidgets.QMessageBox.warning(self, "13F", m))

    def _show_holdings(self, res):
        self.result = res
        meta, pos, total = res["meta"], res["positions"], res["total"]
        notes = "<br>".join(meta.get("notes") or [])
        self.meta.setText(
            "<b>%s</b> · çeyrek sonu %s · dosyalama %s · <a style='color:%s' href='%s'>%s</a>"
            "<br>Toplam %s · %s %s" % (
                meta.get("filer"), meta.get("period"), meta.get("filed"), theme.ACCENT,
                meta.get("info_table_url"), meta.get("accession"), "${:,.0f}".format(total),
                meta.get("total_check", ""), notes))
        self.meta.setOpenExternalLinks(True)
        self.table.setRowCount(len(pos))
        for r, p in enumerate(pos):
            _set_row(self.table, r, [r + 1, p.get("ticker") or "?", p.get("name") or p["issuer"],
                                     "%.2f%%" % p["pct_of_13f"], "${:,.0f}".format(p["value"]),
                                     "{:,.0f}".format(p["shares"]),
                                     "ticker tahmini" if p.get("ticker_check") else
                                     (p.get("put_call") or "")])
        self.tabs.setCurrentIndex(0)
        self.status.emit("%s: %d pozisyon" % (meta.get("filer"), len(pos)))

    def diff(self):
        cik = self._cik()
        if not cik:
            return
        try:
            ua = self._ua()
        except services.ServiceError as exc:
            QtWidgets.QMessageBox.information(self, "SEC kimliği", str(exc))
            return
        run_async(services.quarter_diff, cik, ua, done=self._show_diff,
                  failed=lambda m: QtWidgets.QMessageBox.warning(self, "13F", m))

    def _show_diff(self, res):
        rows = [c for c in res["changes"] if c["status"] != "UNCHANGED"]
        self.diff_table.setRowCount(len(rows))
        colors = {"NEW": theme.UP, "ADDED": theme.UP, "SOLD OUT": theme.DOWN, "TRIMMED": theme.DOWN}
        for r, c in enumerate(rows):
            _set_row(self.diff_table, r, [
                STATUS_TR.get(c["status"], c["status"]), c.get("ticker") or "?", c["issuer"],
                "{:,.0f}".format(c["shares_before"]), "{:,.0f}".format(c["shares_after"]),
                "" if c["change_pct"] is None else "%+.1f%%" % c["change_pct"]],
                {0: colors.get(c["status"])})
        self.tabs.setCurrentIndex(1)
        self.status.emit("%s → %s değişimi" % (res["meta"].get("prior_period"), res["meta"].get("period")))

    def make_targets(self):
        if not self.result:
            QtWidgets.QMessageBox.information(self, "13F", "Önce bir portföy getirin.")
            return
        exclude = [x.strip().upper() for x in self.exclude.text().split(",") if x.strip()]
        try:
            t = services.copy_targets(self.result, top=self.top.value(),
                                      min_pct=self.min_pct.value(), exclude=exclude)
        except services.ServiceError as exc:
            QtWidgets.QMessageBox.warning(self, "13F", str(exc))
            return
        self.targets = t
        self.weights.setRowCount(len(t["weights"]))
        for r, w in enumerate(t["weights"]):
            _set_row(self.weights, r, [w["ticker"] + (" *" if w.get("check_ticker") else ""),
                                       w["name"], "%.2f%%" % w["weight"], "%.2f%%" % w["pct_of_13f"]])
        self.tabs.setCurrentIndex(2)
        self.apply_btn.setEnabled(True)
        self.ctx.settings.update({"copycat": {"cik": self.result["meta"].get("cik"),
                                              "top": self.top.value()}})

    def apply_to_bot(self):
        if not self.targets:
            return
        weights = {w["ticker"]: round(w["weight"] / 100.0, 6) for w in self.targets["weights"]}
        msg = ("Bot bundan sonra %s portföyünün ilk %d pozisyonunu bu ağırlıklarla tutacak "
               "(%s itibarıyla). Tek bir hisseye en fazla %%25 ayrılsın mı? (trader-budget "
               "varsayılanı)" % (self.result["meta"].get("filer"), len(weights),
                                 self.targets["as_of"]))
        ans = QtWidgets.QMessageBox.question(
            self, "Bota uygula", msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel)
        if ans == QtWidgets.QMessageBox.Cancel:
            return
        if ans == QtWidgets.QMessageBox.Yes:
            risk = self.ctx.settings.get("risk")
            risk["max_position_pct"] = 25
            self.ctx.settings.set("risk", risk)
        self.ctx.settings.set("strategy", {"key": "fixed_weights", "params": {"weights": weights}})
        self.ctx.settings_changed.emit()
        self.status.emit("Bot hedefi: %s 13F kopyası" % self.result["meta"].get("filer"))
