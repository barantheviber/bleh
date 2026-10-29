"""Bot tab: controls, account, positions, orders, approvals and the journal."""

import datetime as dt
import logging

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import market_clock, strategies
from . import theme
from .workers import run_async

log = logging.getLogger("traderbot.ui")


def _table(headers, stretch=0):
    t = QtWidgets.QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(stretch, QtWidgets.QHeaderView.Stretch)
    return t


def _set_row(table, r, values, colors=None):
    for c, v in enumerate(values):
        it = QtWidgets.QTableWidgetItem("" if v is None else str(v))
        if c > 0:
            it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if colors and colors.get(c):
            it.setForeground(QtGui.QColor(colors[c]))
        table.setItem(r, c, it)


def money(x):
    if x is None:
        return "—"
    return "${:,.2f}".format(x)


class Card(QtWidgets.QFrame):
    def __init__(self, title):
        super().__init__()
        self.setStyleSheet("QFrame { background: %s; border: 1px solid %s; border-radius: 6px; }"
                           "QLabel { border: none; background: transparent; }"
                           % (theme.PANEL, theme.BORDER))
        self.value = theme.label("—", "big")
        self.sub = theme.label("", "muted")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.addWidget(theme.label(title, "muted"))
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub="", color=None):
        self.value.setText(value)
        self.value.setStyleSheet("color: %s;" % (color or theme.TEXT))
        self.sub.setText(sub)


class BotTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._refreshing = False
        self._again = False
        self._ticking = False

        self.banner = theme.label("", "banner")
        self.banner.setVisible(False)
        self.state_label = theme.label("", "title")
        self.strategy_label = theme.label("", wrap=True)
        self.mode_label = theme.label("", "muted", wrap=True)
        self.start_btn = theme.button("Başlat", "good")
        self.start_btn.clicked.connect(self._toggle)
        run_now = theme.button("Şimdi çalıştır", tip="Bugünün kararını şimdi ver (piyasa açıkken)")
        run_now.clicked.connect(self._run_now)
        dry = theme.button("Kuru çalıştırma", tip="Emir göndermeden bugünün planını göster")
        dry.clicked.connect(self._dry_run)
        self.halt_btn = theme.button("Acil durdur", "danger", tip="Yeni emirleri hemen durdur")
        self.halt_btn.clicked.connect(self._halt_or_resume)
        close_all = theme.button("Tümünü kapat", "danger", tip="Bütün pozisyonları sat ve durdur")
        close_all.clicked.connect(self._close_all)
        buttons = QtWidgets.QHBoxLayout()
        for b in (self.start_btn, run_now, dry, self.halt_btn, close_all):
            buttons.addWidget(b)
        buttons.addStretch(1)

        self.cards = {k: Card(t) for k, t in (("equity", "Toplam varlık"), ("cash", "Nakit"),
                                             ("day", "Bugün"), ("total", "Toplam getiri"),
                                             ("dd", "Zirveden düşüş"))}
        cards = QtWidgets.QHBoxLayout()
        for c in self.cards.values():
            cards.addWidget(c)

        self.targets = _table(["Sembol", "Hedef %", "Şimdi %", "Fark (puan)"])
        self.positions = _table(["Sembol", "Adet", "Ort. maliyet", "Fiyat", "Değer", "K/Z", "K/Z %"])
        self.pending = _table(["Emir", "Neden", ""], stretch=1)
        self.orders = _table(["Zaman", "Sembol", "Yön", "Miktar", "Durum", "Dolum fiyatı"], stretch=0)
        self.journal = QtWidgets.QListWidget()
        self.journal.setWordWrap(True)
        self.equity_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.equity_plot.showGrid(x=True, y=True, alpha=0.15)
        self.equity_plot.setMenuEnabled(False)
        self.equity_curve = self.equity_plot.plot(pen=pg.mkPen(theme.ACCENT, width=2),
                                                  fillLevel=0, brush=pg.mkBrush(47, 129, 247, 30))
        self.equity_empty = pg.TextItem("Bot çalıştıkça varlık eğrisi burada oluşur",
                                        color=theme.MUTED, anchor=(0.5, 0.5))
        self.equity_plot.addItem(self.equity_empty)
        self.equity_plot.getAxis("bottom").setStyle(showValues=False)
        self.equity_plot.getAxis("left").setStyle(showValues=False)

        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(theme.label("Bugünün hedefleri", "title"))
        ll.addWidget(self.targets, 2)
        ll.addWidget(theme.label("Pozisyonlar", "title"))
        ll.addWidget(self.positions, 3)
        self.pending_title = theme.label("Onay bekleyen emirler", "title")
        ll.addWidget(self.pending_title)
        ll.addWidget(self.pending, 2)
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(theme.label("Varlık eğrisi", "title"))
        rl.addWidget(self.equity_plot, 3)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.journal, "Karar günlüğü")
        tabs.addTab(self.orders, "Emir geçmişi")
        rl.addWidget(tabs, 4)
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 620])

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.banner)
        head = QtWidgets.QHBoxLayout()
        info = QtWidgets.QVBoxLayout()
        info.addWidget(self.state_label)
        info.addWidget(self.strategy_label)
        info.addWidget(self.mode_label)
        head.addLayout(info, 1)
        lay.addLayout(head)
        lay.addLayout(buttons)
        lay.addLayout(cards)
        lay.addWidget(split, 1)

        ctx.event.connect(self._on_event)
        ctx.broker_changed.connect(self.refresh)
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(10000)
        self.tick_timer = QtCore.QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(30000)
        self._load_journal()

    # ------------------------------------------------------------ engine

    def tick(self):
        if self._ticking:
            return
        self._ticking = True
        run_async(self.ctx.engine.tick, done=self._ticked, failed=self._tick_failed)

    def _ticked(self, res):
        self._ticking = False
        if res and res.get("ran"):
            self.refresh()

    def _tick_failed(self, msg):
        self._ticking = False
        self.status.emit("Bot adımı başarısız: %s" % msg)

    def _toggle(self):
        eng = self.ctx.engine
        if eng.snapshot()["running"]:
            eng.stop()
        else:
            if self.ctx.is_live():
                ok = QtWidgets.QMessageBox.warning(
                    self, "CANLI HESAP", "Bot GERÇEK PARA ile işlem yapacak. Emin misiniz?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No)
                if ok != QtWidgets.QMessageBox.Yes:
                    return
            eng.start()
            self.tick()
        self.refresh()

    def _run_now(self):
        st = market_clock.status()
        if not st["open"]:
            QtWidgets.QMessageBox.information(
                self, "Piyasa kapalı", "NYSE şu an kapalı (%s). Bot açılışta kendisi çalışır; "
                "planı şimdi görmek için 'Kuru çalıştırma'yı kullanın." % st["reason"])
            return
        mode = "emirleri GÖNDERECEK" if self.ctx.settings.get("auto_trade") else \
            "emirleri onayınıza sunacak"
        if QtWidgets.QMessageBox.question(self, "Şimdi çalıştır",
                                          "Bot bugünün kararını şimdi verecek ve %s. Devam?" % mode) \
                != QtWidgets.QMessageBox.Yes:
            return
        self.status.emit("Bot çalışıyor…")
        run_async(self.ctx.engine.run_cycle, done=self._cycle_done,
                  failed=lambda m: self.status.emit("Çalıştırma başarısız: %s" % m))

    def _dry_run(self):
        self.status.emit("Plan hesaplanıyor…")
        run_async(self.ctx.engine.run_cycle, dry_run=True, done=self._show_plan,
                  failed=lambda m: self.status.emit("Plan başarısız: %s" % m))

    def _cycle_done(self, res):
        if not res.get("ok"):
            QtWidgets.QMessageBox.warning(self, "Bot", res.get("error") or "Başarısız")
        self._show_targets(res)
        self.refresh()

    def _show_plan(self, res):
        if not res.get("ok"):
            QtWidgets.QMessageBox.warning(self, "Plan", res.get("error") or "Başarısız")
            return
        self._show_targets(res)
        weights = ", ".join("%s %%%.1f" % (s, w) for s, w in res["targets"]["weights"].items())
        lines = ["<b>%s</b> · veri: %s kapanışı" % (res["targets"]["name"], res["targets"]["as_of"]),
                 "Hedef: " + (weights or "tamamı nakit")]
        if res["orders"]:
            lines.append("<br><b>Emirler</b> (sırayla):")
            blocked = {(b["symbol"], b["side"]) for b in res["blocked"]}
            for o in res["orders"]:
                amt = ("$" + o["notional"]) if o.get("notional") else ("%s adet" % o.get("qty"))
                tag = " <span style='color:%s'>ENGELLENDİ</span>" % theme.DOWN \
                    if (o["symbol"], o["side"]) in blocked else ""
                lines.append("• %s %s %s%s<br>&nbsp;&nbsp;<i>%s</i>" % (
                    "AL" if o["side"] == "buy" else "SAT", o["symbol"], amt, tag, o.get("why", "")))
            for b in res["blocked"]:
                lines.append("<span style='color:%s'>%s: %s</span>" % (
                    theme.DOWN, b["symbol"], "; ".join(b["reasons"])))
        else:
            lines.append("<br>Bant içinde: bugün işlem gerekmiyor.")
        for n in res.get("notes") or []:
            lines.append("<i>%s</i>" % n)
        QtWidgets.QMessageBox.information(self, "Bugünün planı (kuru çalıştırma)", "<br>".join(lines))
        self.status.emit("Plan hazır")

    def _halt_or_resume(self):
        eng = self.ctx.engine
        if eng.snapshot()["halted"]:
            eng.resume()
        else:
            eng.halt("Kullanıcı acil durdurdu")
        self.refresh()

    def _close_all(self):
        if QtWidgets.QMessageBox.warning(
                self, "Tümünü kapat", "Bütün pozisyonlar piyasa fiyatından satılacak ve bot "
                "duracak. Emin misiniz?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        run_async(self.ctx.engine.close_all, done=lambda r: self.refresh(),
                  failed=lambda m: QtWidgets.QMessageBox.critical(self, "Hata", m))

    def _approve(self, fp):
        run_async(self.ctx.engine.approve, fp, done=lambda r: self.refresh(),
                  failed=lambda m: QtWidgets.QMessageBox.warning(self, "Onay", m))

    def _reject(self, fp):
        self.ctx.engine.reject(fp)
        self.refresh()

    # ------------------------------------------------------------ display

    def refresh(self):
        self._show_state()
        if self._refreshing:
            # one fetch is in flight: run another when it lands, never show stale data
            self._again = True
            return
        self._refreshing = True
        self._again = False
        broker = self.ctx.broker

        def fetch():
            return {"account": broker.account(), "positions": broker.positions(),
                    "orders": broker.orders(limit=100)}

        run_async(fetch, done=self._show, failed=self._show_failed)

    def _landed(self):
        self._refreshing = False
        if getattr(self, "_again", False):
            QtCore.QTimer.singleShot(0, self.refresh)

    def _show_failed(self, msg):
        self._landed()
        self.cards["equity"].set("—", "hesap okunamadı: %s" % msg[:60], theme.DOWN)

    def _show_state(self):
        st = self.ctx.engine.snapshot()
        s = self.ctx.settings
        live = self.ctx.is_live()
        self.banner.setVisible(live)
        self.banner.setText("CANLI HESAP — GERÇEK PARA · %s" % self.ctx.broker.label)
        if st["halted"] and st.get("halt_kind") == "auto":
            self.state_label.setText("Bot: ACİL DURUM — yalnız satış")
            self.state_label.setStyleSheet("color: %s;" % theme.WARN)
        elif st["halted"]:
            self.state_label.setText("Bot: ACİL DURDURULDU")
            self.state_label.setStyleSheet("color: %s;" % theme.DOWN)
        elif st["running"]:
            self.state_label.setText("Bot: ÇALIŞIYOR")
            self.state_label.setStyleSheet("color: %s;" % theme.UP)
        else:
            self.state_label.setText("Bot: DURDU")
            self.state_label.setStyleSheet("color: %s;" % theme.MUTED)
        self.start_btn.setText("Durdur" if st["running"] else "Başlat")
        self.start_btn.setProperty("kind", "danger" if st["running"] else "good")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.halt_btn.setText("Devam et" if st["halted"] else "Acil durdur")
        spec = s.get("strategy") or {}
        cls = strategies.REGISTRY.get(spec.get("key"))
        if cls:
            params = ", ".join("%s=%s" % kv for kv in sorted((spec.get("params") or {}).items())
                               if not isinstance(kv[1], (list, dict)))
            self.strategy_label.setText("<b>%s</b> (%s) — %s" % (cls.name, params, cls.summary))
        mode = "Tam otomatik" if s.get("auto_trade") else "Her emir onayınızla"
        nxt = self._next_run(st)
        why = (" · <span style='color:%s'>%s</span>" % (theme.DOWN, st["halt_reason"])) \
            if st["halted"] else ""
        err = (" · <span style='color:%s'>Aracı: %s</span>" % (theme.WARN, self.ctx.broker_error)) \
            if self.ctx.broker_error else ""
        self.mode_label.setText("%s · %s · günde bir kez, NY %s sonrası · %s%s%s"
                                % (mode, self.ctx.broker.label, s.get("trade_time"), nxt, why, err))
        self._show_pending(st["pending"])
        last = st.get("last_cycle")
        if last and last.get("targets") and not self.targets.rowCount():
            self._show_targets({"targets": last["targets"], "rows": []})
        hist = st.get("equity_history") or []
        self.equity_empty.setVisible(len(hist) < 2)
        self.equity_plot.getAxis("bottom").setStyle(showValues=len(hist) >= 2)
        self.equity_plot.getAxis("left").setStyle(showValues=len(hist) >= 2)
        if hist:
            xs = [_ts(h[0]) for h in hist]
            ys = [h[1] for h in hist]
            self.equity_curve.setData(xs, ys)
            lo, hi = min(ys), max(ys)
            pad = (hi - lo) * 0.1 or hi * 0.01 or 1
            self.equity_plot.setYRange(lo - pad, hi + pad)
            self.equity_curve.setFillLevel(lo - pad)

    def _next_run(self, st):
        ny = market_clock.ny_now()
        today = ny.date()
        sess = market_clock.session(today)
        if st["last_run_date"] == today.isoformat() or sess is None or ny >= sess[1]:
            day = market_clock.next_trading_day(today)
        else:
            day = today
        return "sonraki karar: %s NY %s" % (day.strftime("%d.%m.%Y"), self.ctx.settings.get("trade_time"))

    def _show(self, data):
        self._landed()
        acct, pos, orders = data["account"], data["positions"], data["orders"]
        st = self.ctx.engine.snapshot()
        start = (st.get("day") or {}).get("start_equity")
        peak = st.get("peak_equity")
        self.cards["equity"].set(money(acct.equity), acct.broker or "")
        self.cards["cash"].set(money(acct.cash), "alım gücü %s" % money(acct.buying_power))
        if start:
            d = acct.equity - start
            self.cards["day"].set("%+.2f%%" % (100 * d / start), money(d), theme.color_for(d))
        base = getattr(self.ctx.broker, "state", {}).get("start_cash") \
            if hasattr(self.ctx.broker, "state") else None
        if base:
            t = acct.equity - base
            self.cards["total"].set("%+.2f%%" % (100 * t / base), "%s başlangıca göre" % money(base),
                                    theme.color_for(t))
        else:
            self.cards["total"].set("—", "aracının kendi raporuna bakın")
        if peak:
            dd = acct.equity / peak - 1
            self.cards["dd"].set("%.2f%%" % (100 * dd), "zirve %s" % money(peak),
                                 theme.DOWN if dd < -0.0001 else theme.MUTED)
        self.positions.setRowCount(len(pos))
        for r, p in enumerate(pos):
            _set_row(self.positions, r, [p.symbol, "%.4f" % p.qty, "%.2f" % p.avg_price,
                                         "" if p.price is None else "%.2f" % p.price,
                                         money(p.market_value), money(p.unrealized_pl),
                                         "%+.2f%%" % (100 * p.unrealized_pct)],
                     {5: theme.color_for(p.unrealized_pl), 6: theme.color_for(p.unrealized_pl)})
        self.orders.setRowCount(len(orders))
        for r, o in enumerate(orders):
            amt = ("$%s" % o.notional) if o.notional else ("%s adet" % (o.qty or o.filled_qty))
            _set_row(self.orders, r, [(o.filled_at or o.created_at or "")[:19].replace("T", " "),
                                      o.symbol, "AL" if o.side == "buy" else "SAT", amt, o.status,
                                      "" if o.filled_avg_price is None else "%.2f" % o.filled_avg_price],
                     {2: theme.UP if o.side == "buy" else theme.DOWN})
        # current weights next to the targets
        if self.targets.rowCount() and acct.equity > 0:
            cur = {p.symbol: 100 * p.market_value / acct.equity for p in pos}
            for r in range(self.targets.rowCount()):
                sym = self.targets.item(r, 0).text()
                tgt = float(self.targets.item(r, 1).text().rstrip("%") or 0)
                now = cur.get(sym, 0.0)
                _set_row(self.targets, r, [sym, "%.1f%%" % tgt, "%.1f%%" % now, "%+.1f" % (now - tgt)],
                         {3: theme.WARN if abs(now - tgt) > float(
                             (self.ctx.settings.get("risk") or {}).get("rebalance_band_pct") or 5)
                          else theme.MUTED})

    def _show_targets(self, res):
        t = (res.get("targets") or {}).get("weights") or {}
        self.targets.setRowCount(len(t))
        for r, (sym, w) in enumerate(sorted(t.items(), key=lambda kv: -kv[1])):
            _set_row(self.targets, r, [sym, "%.1f%%" % w, "", ""])

    def _show_pending(self, pending):
        auto = self.ctx.settings.get("auto_trade")
        self.pending.setVisible(not auto or bool(pending))
        self.pending_title.setVisible(not auto or bool(pending))
        self.pending.setRowCount(len(pending))
        for r, o in enumerate(pending):
            amt = ("$" + str(o["notional"])) if o.get("notional") else ("%s adet" % o.get("qty"))
            _set_row(self.pending, r, ["%s %s %s" % ("AL" if o["side"] == "buy" else "SAT",
                                                     o["symbol"], amt), o.get("why", ""), ""])
            box = QtWidgets.QWidget()
            bl = QtWidgets.QHBoxLayout(box)
            bl.setContentsMargins(2, 2, 2, 2)
            yes = theme.button("Onayla", "good")
            no = theme.button("Reddet")
            fp = o.get("fingerprint")
            yes.clicked.connect(lambda _=False, f=fp: self._approve(f))
            no.clicked.connect(lambda _=False, f=fp: self._reject(f))
            bl.addWidget(yes)
            bl.addWidget(no)
            self.pending.setCellWidget(r, 2, box)

    # ------------------------------------------------------------ journal

    def _load_journal(self):
        import json
        try:
            with open(self.ctx.engine.journal_path, encoding="utf-8") as fh:
                lines = fh.readlines()[-200:]
        except OSError:
            return
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            self._add_journal(rec)

    def _on_event(self, kind, rec):
        self._add_journal(rec)
        if kind in ("order", "plan", "halted", "closed_all", "approval"):
            self.refresh()
        if kind == "plan" and rec.get("targets") is not None:
            self._show_targets({"targets": {"weights": rec.get("targets")}})
        if kind in ("halted", "error"):
            self.status.emit(rec.get("message", ""))

    def _add_journal(self, rec):
        when = (rec.get("at") or "")[:16].replace("T", " ")
        kind = rec.get("kind", "")
        color = {"error": theme.DOWN, "halted": theme.DOWN, "order": theme.UP,
                 "warning": theme.WARN, "approval": theme.WARN}.get(kind, theme.TEXT)
        item = QtWidgets.QListWidgetItem("%s UTC  %s" % (when, rec.get("message", kind)))
        item.setForeground(QtGui.QColor(color))
        self.journal.insertItem(0, item)
        while self.journal.count() > 500:
            self.journal.takeItem(self.journal.count() - 1)


def _ts(text):
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0
