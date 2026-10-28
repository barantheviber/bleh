"""The trading bot: once per trading day, turn the strategy's target weights
into orders and place them.

One cycle, after `trade_time` (New York) on a day NYSE is open:
  1. daily bars up to yesterday's close -> strategy.weights() -> today's targets
  2. trader-rebalance plan(): the trades that bring each holding back to its
     target when it drifted past the band (sells first, buys in dollars)
  3. trader-risk check(): every order PASS or BLOCK against the risk rules
  4. passed orders go to the broker (auto mode) or wait for approval

Every tick also values the account and trips the kill switches: a day's loss
or a drop from the peak beyond the limits halts all new orders until the
user resumes. The engine has no Qt in it; the UI calls tick() on a timer.
"""

import datetime as dt
import json
import os
import threading
import time
import traceback

import numpy as np

from . import market_clock, paths, strategies
from .backtest import build_panel
from .brokers import BrokerError
from .data.yahoo import DataError
from .skills import check as risk_check
from .skills import rebalance

STATE_VERSION = 1
KEEP_PLACED_DAYS = 10


class EngineError(Exception):
    pass


def default_state():
    return {"version": STATE_VERSION, "running": False, "halted": False, "halt_reason": "",
            "last_run_date": None, "day": {}, "peak_equity": None, "pending": [],
            "placed": [], "equity_history": [], "last_cycle": None}


class BotEngine(object):
    def __init__(self, settings, broker, data, state_path=None, journal_path=None,
                 now=market_clock.utc_now, on_event=None, sleep=time.sleep):
        self.settings = settings
        self.broker = broker
        self.data = data
        self.state_path = state_path or paths.path("bot_state.json")
        self.journal_path = journal_path or paths.path("journal.jsonl")
        self.now = now
        self.on_event = on_event or (lambda kind, payload: None)
        self.sleep = sleep
        self._lock = threading.RLock()
        self._busy = threading.Lock()
        self.state = self._load()

    # ------------------------------------------------------------ state

    def _load(self):
        st = default_state()
        if os.path.isfile(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as fh:
                    st.update(json.load(fh))
            except (OSError, ValueError):
                os.replace(self.state_path, self.state_path + ".broken")
        return st

    def _save(self):
        with self._lock:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, indent=1, default=str)
            os.replace(tmp, self.state_path)

    def _journal(self, kind, **payload):
        rec = {"at": self.now().replace(microsecond=0).isoformat() + "Z", "kind": kind}
        rec.update(payload)
        try:
            with open(self.journal_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self.on_event(kind, rec)
        return rec

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.state, default=str))

    # ------------------------------------------------------------ controls

    def start(self):
        with self._lock:
            self.state["running"] = True
            self._save()
        self._journal("started", message="Bot başlatıldı (%s, %s)" % (
            self.broker.label, "otomatik" if self.settings.get("auto_trade") else "onaylı"))

    def stop(self):
        with self._lock:
            self.state["running"] = False
            self._save()
        self._journal("stopped", message="Bot durduruldu")

    def halt(self, reason):
        with self._lock:
            self.state["halted"] = True
            self.state["halt_reason"] = reason
            self.state["pending"] = []
            self._save()
        self._journal("halted", message="ACİL DURDURMA: %s" % reason)

    def resume(self):
        with self._lock:
            self.state["halted"] = False
            self.state["halt_reason"] = ""
            # a resumed bot measures its next drawdown from here
            self.state["peak_equity"] = None
            self.state["day"] = {}
            self._save()
        self._journal("resumed", message="Acil durdurma kaldırıldı")

    def close_all(self):
        """Panic button: sell everything and halt."""
        self.halt("Kullanıcı tüm pozisyonları kapattı")
        try:
            done = self.broker.close_all()
        except BrokerError as exc:
            self._journal("error", message="Pozisyonlar kapatılamadı: %s" % exc)
            raise
        self._journal("closed_all", message="%d pozisyon kapatıldı" % len(done))
        return done

    # ------------------------------------------------------------ the loop

    def tick(self):
        """Called every few seconds by the UI. Never raises: problems are
        journaled so a bad network minute cannot kill the bot."""
        if not self._busy.acquire(False):
            return None
        try:
            return self._tick()
        except Exception as exc:  # last line of defence for an unattended bot
            self._journal("error", message="Beklenmeyen hata: %s" % exc,
                          trace=traceback.format_exc(limit=5))
            return None
        finally:
            self._busy.release()

    def _tick(self):
        with self._lock:
            running = self.state["running"]
        status = market_clock.status(self.now())
        equity = self._value_account(status)
        if not running or equity is None:
            return {"status": status, "equity": equity, "ran": False}
        self._kill_switches(equity, status)
        with self._lock:
            halted = self.state["halted"]
            done_today = self.state["last_run_date"] == status["ny"].date().isoformat()
        if halted or done_today or not status["open"]:
            return {"status": status, "equity": equity, "ran": False}
        if status["ny"].time() < _parse_time(self.settings.get("trade_time") or "10:00"):
            return {"status": status, "equity": equity, "ran": False}
        if self.broker.is_open() is False:
            # the broker knows about closures our calendar cannot (e.g. a day of mourning)
            return {"status": status, "equity": equity, "ran": False}
        result = self.run_cycle()
        return {"status": status, "equity": equity, "ran": True, "cycle": result}

    def _value_account(self, status):
        try:
            acct = self.broker.account()
        except BrokerError as exc:
            self._journal("error", message="Hesap okunamadı: %s" % exc)
            return None
        today = status["ny"].date().isoformat()
        with self._lock:
            day = self.state.get("day") or {}
            if day.get("date") != today:
                self.state["day"] = {"date": today, "start_equity": acct.equity}
                self.state["pending"] = [p for p in self.state["pending"]
                                         if p.get("date") == today]
            peak = self.state.get("peak_equity")
            self.state["peak_equity"] = acct.equity if peak is None else max(peak, acct.equity)
            hist = self.state["equity_history"]
            stamp = self.now().replace(second=0, microsecond=0).isoformat() + "Z"
            if not hist or hist[-1][0] != stamp:
                hist.append([stamp, round(acct.equity, 2)])
                del hist[:-5000]
            self._save()
        return acct.equity

    def _kill_switches(self, equity, status):
        risk = self.settings.get("risk") or {}
        with self._lock:
            if self.state["halted"]:
                return
            start = (self.state.get("day") or {}).get("start_equity")
            peak = self.state.get("peak_equity")
        day_lim = float(risk.get("max_daily_loss_pct") or 0)
        dd_lim = float(risk.get("max_drawdown_pct") or 0)
        if day_lim and start and equity < start * (1 - day_lim / 100.0):
            self.halt("Günlük zarar sınırı aşıldı: %.2f%% (sınır %%%g)"
                      % (100 * (equity / start - 1), day_lim))
        elif dd_lim and peak and equity < peak * (1 - dd_lim / 100.0):
            self.halt("Zirveden düşüş sınırı aşıldı: %.2f%% (sınır %%%g)"
                      % (100 * (equity / peak - 1), dd_lim))

    # ------------------------------------------------------------ one cycle

    def strategy(self):
        spec = self.settings.get("strategy") or {}
        return strategies.create(spec.get("key"), **(spec.get("params") or {}))

    def targets(self, status=None):
        """Today's target weights in percent, from bars up to the last close.
        Returns (weights, info)."""
        status = status or market_clock.status(self.now())
        strat = self.strategy()
        syms = list(dict.fromkeys(strat.inputs()))
        bars = self.data.daily(syms)
        today = status["ny"].date()
        last_close = today if (status["state"] in ("post", "closed")
                               and market_clock.is_trading_day(today)) \
            else market_clock.prev_trading_day(today)
        clipped = {}
        for s, b in bars.items():
            keep = np.nonzero(b.dates() <= np.datetime64(last_close))[0]
            b = b.take(keep)
            if not len(b):
                raise EngineError("%s için hiç tamamlanmış günlük bar yok" % s)
            clipped[s] = b
        newest = min(np.datetime64(b.dates()[-1]) for b in clipped.values())
        if newest < np.datetime64(market_clock.prev_trading_day(last_close)):
            raise EngineError("Veri güncel değil: en eski son bar %s, beklenen %s"
                              % (newest, last_close))
        panel = build_panel(clipped, calendar_symbol=syms[0])
        last_bar = panel.dates[-1].astype(dt.date)
        panel.next_session = market_clock.next_trading_day(last_bar)
        W = strat.weights(panel)
        row = W[-1]
        if not np.all(np.isfinite(row)):
            raise EngineError("Strateji henüz hazır değil (geçmiş veri yetersiz)")
        weights = {s: round(100.0 * float(w), 4) for s, w in zip(strat.symbols(), row)
                   if w > 1e-6}
        info = {"strategy": strat.label(), "name": strat.name, "as_of": str(panel.dates[-1]),
                "weights": weights}
        return weights, info

    def _skill_cfg(self, equity):
        risk = self.settings.get("risk") or {}
        cfg = dict(risk)
        if not cfg.get("max_order_usd"):
            cfg["max_order_usd"] = max(float(equity), 1.0)
        cfg["fractional"] = True
        cfg["paper"] = bool(self.broker.paper)
        return cfg

    def run_cycle(self, dry_run=False):
        """Plan, check and (unless dry_run) place today's orders."""
        status = market_clock.status(self.now())
        today = status["ny"].date().isoformat()
        try:
            weights, info = self.targets(status)
        except (DataError, EngineError) as exc:
            self._journal("error", message="Hedef hesaplanamadı: %s" % exc)
            return {"ok": False, "error": str(exc)}
        try:
            portfolio = self.broker.portfolio()
            held = [p["ticker"] for p in portfolio["positions"]]
            prices = self.data.prices(sorted(set(weights) | set(held)), fresh=True)
            equity = portfolio["cash"] + sum(p["shares"] * prices.get(p["ticker"], 0)
                                             for p in portfolio["positions"])
            cfg = self._skill_cfg(equity)
            plan = rebalance.plan(portfolio, prices, weights, cfg,
                                  band=cfg.get("rebalance_band_pct"),
                                  sell_untracked=bool(self.settings.get("sell_untracked")))
            orders = rebalance.clean(plan["orders"])
            with self._lock:
                placed = list(self.state["placed"])
            verdict = risk_check.check(orders, cfg, portfolio, prices, {"orders": placed}, today)
        except (BrokerError, DataError, rebalance.RebalanceError, risk_check.RiskError) as exc:
            self._journal("error", message="Plan yapılamadı: %s" % exc)
            return {"ok": False, "error": str(exc)}
        passed = [o for o, r in zip(orders, verdict["results"]) if r["verdict"] == "PASS"]
        blocked = [dict(r, order=o) for o, r in zip(orders, verdict["results"])
                   if r["verdict"] != "PASS"]
        summary = {"ok": True, "date": today, "targets": info, "rows": plan["rows"],
                   "notes": plan["notes"], "orders": orders, "passed": len(passed),
                   "blocked": blocked, "dry_run": dry_run, "placed": []}
        self._journal("plan", message="%s: %d emir, %d geçti, %d engellendi" % (
            info["name"], len(orders), len(passed), len(blocked)),
            targets=info["weights"], as_of=info["as_of"], orders=orders,
            blocked=[{"symbol": b["symbol"], "reasons": b["reasons"]} for b in blocked])
        if dry_run:
            return summary
        if self.settings.get("auto_trade"):
            summary["placed"] = self.execute(passed, today)
        else:
            with self._lock:
                self.state["pending"] = [dict(o, date=today, fingerprint=risk_check.fingerprint(o))
                                         for o in passed]
            if passed:
                self._journal("approval", message="%d emir onay bekliyor" % len(passed))
        with self._lock:
            self.state["last_run_date"] = today
            self.state["last_cycle"] = {k: summary[k] for k in ("date", "targets", "passed",
                                                                 "notes", "dry_run")}
            self.state["last_cycle"]["blocked"] = len(blocked)
            self._save()
        return summary

    def execute(self, orders, today=None):
        """Place orders: sells first, then buys sized to the cash actually there."""
        today = today or market_clock.status(self.now())["ny"].date().isoformat()
        sells = [o for o in orders if o["side"] == "sell"]
        buys = [o for o in orders if o["side"] == "buy"]
        out = []
        for o in sells:
            out.append(self._place(o, today))
        if sells and buys:
            self._wait_filled([r["id"] for r in out if r.get("id")])
        if buys:
            try:
                acct = self.broker.account()
                risk = self.settings.get("risk") or {}
                buffer_usd = acct.equity * float(risk.get("cash_buffer_pct") or 0) / 100.0
                free = max(0.0, acct.cash - buffer_usd)
            except BrokerError as exc:
                self._journal("error", message="Alımdan önce hesap okunamadı: %s" % exc)
                return out
            want = sum(float(o.get("notional") or 0) for o in buys)
            scale = min(1.0, free / want) if want > 0 else 1.0
            min_order = float((self.settings.get("risk") or {}).get("min_order_usd") or 0)
            for o in buys:
                o = dict(o)
                if o.get("notional") is not None and scale < 1.0:
                    usd = int(float(o["notional"]) * scale)
                    if usd < max(min_order, 1):
                        self._journal("skipped", message="%s alımı atlandı: nakit yetmedi" % o["symbol"])
                        continue
                    o["notional"] = str(usd)
                out.append(self._place(o, today))
        return out

    def approve(self, fingerprint):
        with self._lock:
            match = [p for p in self.state["pending"] if p.get("fingerprint") == fingerprint]
            self.state["pending"] = [p for p in self.state["pending"]
                                     if p.get("fingerprint") != fingerprint]
            self._save()
        if not match:
            raise EngineError("Bu emir artık bekleyenler arasında değil")
        order = {k: v for k, v in match[0].items() if k not in ("date", "fingerprint")}
        return self.execute([order], match[0].get("date"))

    def reject(self, fingerprint):
        with self._lock:
            self.state["pending"] = [p for p in self.state["pending"]
                                     if p.get("fingerprint") != fingerprint]
            self._save()
        self._journal("rejected", message="Emir reddedildi")

    def _place(self, order, today):
        rec = {"date": today, "symbol": order["symbol"], "side": order["side"],
               "qty": order.get("qty"), "notional": order.get("notional")}
        try:
            o = self.broker.submit(order)
            rec.update(status="placed", id=o.id, broker_status=o.status,
                       filled_qty=o.filled_qty, price=o.filled_avg_price)
            self._journal("order", message="%s %s %s → %s" % (
                "AL" if order["side"] == "buy" else "SAT", order["symbol"],
                ("$" + str(order["notional"])) if order.get("notional") else
                ("%s adet" % order.get("qty")), o.status), order=order, broker_id=o.id)
        except BrokerError as exc:
            rec.update(status="failed", error=str(exc))
            self._journal("error", message="Emir gönderilemedi (%s %s): %s"
                          % (order["side"], order["symbol"], exc), order=order)
        with self._lock:
            cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_PLACED_DAYS)).isoformat()
            self.state["placed"] = [p for p in self.state["placed"] if p["date"] >= cutoff] + [rec]
            self._save()
        return rec

    def _wait_filled(self, ids, timeout=60.0, step=2.0):
        """Give sells time to fill before buying with their cash."""
        left = set(ids)
        waited = 0.0
        while left and waited < timeout:
            for oid in list(left):
                try:
                    if self.broker.get_order(oid).done:
                        left.discard(oid)
                except BrokerError:
                    left.discard(oid)
            if left:
                self.sleep(step)
                waited += step
        if left:
            self._journal("warning", message="%d satış emri %ds içinde dolmadı" % (len(left), timeout))


def _parse_time(text):
    try:
        h, m = [int(x) for x in str(text).split(":", 1)]
        return dt.time(h, m)
    except (ValueError, TypeError):
        return dt.time(10, 0)
