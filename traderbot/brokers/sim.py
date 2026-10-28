"""Built-in simulated (paper) account.

Market orders fill at the latest Yahoo price plus slippage, fractional shares,
no margin, no short selling. US stocks and ETFs fill only during NYSE hours;
symbols with an exchange suffix (THYAO.IS) or a currency pair (BTC-USD) fill
any time at their latest price. The account lives in one JSON file.
"""

import datetime as dt
import json
import os
import re
import threading
import uuid

from .. import market_clock
from .base import Account, Broker, BrokerError, Order, Position

EPS = 1e-9


def us_listed(symbol):
    """US stocks and ETFs trade NYSE hours; BRK.B / BRK-B is a US share class,
    THYAO.IS or BTC-USD is not."""
    if re.fullmatch(r"[A-Z]{1,5}[.-][ABC]", symbol):
        return True
    return "." not in symbol and "-" not in symbol and "=" not in symbol and "^" not in symbol


class SimBroker(Broker):
    name = "Simülasyon"
    paper = True

    def __init__(self, path, price_source, start_cash=10000.0, slippage_bps=2.0,
                 clock=market_clock.status, now=market_clock.utc_now):
        self.path = path
        self.price_source = price_source
        self.slippage = slippage_bps / 1e4
        self.clock = clock
        self.now = now
        self._lock = threading.RLock()
        self.state = None
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.state = json.load(fh)
            except (OSError, ValueError):
                os.replace(path, path + ".broken")
        if self.state is None:
            self.reset(start_cash)

    # ------------------------------------------------------------ state

    def reset(self, cash):
        with self._lock:
            self.state = {"cash": float(cash), "start_cash": float(cash), "positions": {},
                          "orders": [], "created": self._stamp()}
            self._save()

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, indent=1)
        os.replace(tmp, self.path)

    def _stamp(self):
        return self.now().replace(microsecond=0).isoformat() + "Z"

    def _prices(self, symbols):
        if not symbols:
            return {}
        try:
            got = self.price_source(sorted(symbols)) or {}
        except Exception as exc:  # the data source is outside our control
            raise BrokerError("Fiyat alınamadı: %s" % exc)
        return {s: float(p) for s, p in got.items() if p}

    # ------------------------------------------------------------ queries

    def positions(self, prices=None):
        with self._lock:
            held = {s: p for s, p in self.state["positions"].items() if abs(p["qty"]) > EPS}
        px = prices if prices is not None else self._prices(held)
        return [Position(s, p["qty"], p["cost"] / p["qty"], px.get(s))
                for s, p in sorted(held.items())]

    def account(self, prices=None):
        pos = self.positions(prices)
        with self._lock:
            cash = self.state["cash"]
        equity = cash + sum(p.market_value for p in pos)
        return Account(cash, equity, cash, "USD", True, "ACTIVE", self.name)

    def orders(self, limit=100):
        with self._lock:
            rows = list(self.state["orders"][-limit:])
        return [Order(**r) for r in reversed(rows)]

    def get_order(self, order_id):
        with self._lock:
            for r in self.state["orders"]:
                if r["id"] == order_id:
                    return Order(**r)
        raise BrokerError("Emir bulunamadı: %s" % order_id)

    def is_open(self):
        return bool(self.clock(self.now())["open"])

    # ------------------------------------------------------------ trading

    def submit(self, order, price=None):
        """Fill a market order now. `price` skips the quote lookup (tests,
        or a price the caller just fetched)."""
        sym = str(order.get("symbol", "")).strip().upper()
        side = str(order.get("side", "")).lower()
        typ = str(order.get("type", "market")).lower()
        qty = _num(order.get("qty"))
        notional = _num(order.get("notional"))
        if not sym or side not in ("buy", "sell"):
            raise BrokerError("Geçersiz emir: sembol ve yön (buy/sell) gerekli")
        if typ != "market":
            raise BrokerError("Simülasyonda yalnızca piyasa emri (market) var")
        if (qty is None) == (notional is None) or (qty or notional or 0) <= 0:
            raise BrokerError("Emirde ya adet (qty) ya tutar (notional) olmalı, pozitif")
        if us_listed(sym) and not self.clock(self.now())["open"]:
            raise BrokerError("NYSE kapalı: ABD hissesi emri seans içinde verilmeli")
        if price is None:
            price = self._prices([sym]).get(sym)
        if not price or price <= 0:
            raise BrokerError("%s için fiyat yok" % sym)
        fill = price * (1 + self.slippage) if side == "buy" else price * (1 - self.slippage)
        with self._lock:
            pos = self.state["positions"].get(sym, {"qty": 0.0, "cost": 0.0})
            if side == "buy":
                q = qty if qty is not None else notional / fill
                cost = q * fill
                if cost > self.state["cash"] + 0.005:
                    raise BrokerError("Yetersiz nakit: %.2f $ gerekli, %.2f $ var (kaldıraç kapalı)"
                                      % (cost, self.state["cash"]))
                self.state["cash"] -= cost
                pos = {"qty": pos["qty"] + q, "cost": pos["cost"] + cost}
            else:
                q = qty if qty is not None else notional / fill
                if q > pos["qty"] + 1e-6:
                    raise BrokerError("%s: elinizde %.4f adet var, %.4f satılamaz (açığa satış kapalı)"
                                      % (sym, pos["qty"], q))
                q = min(q, pos["qty"])
                avg = pos["cost"] / pos["qty"] if pos["qty"] > EPS else 0.0
                self.state["cash"] += q * fill
                left = pos["qty"] - q
                pos = {"qty": left, "cost": avg * left} if left > 1e-9 else {"qty": 0.0, "cost": 0.0}
            if pos["qty"] > EPS:
                self.state["positions"][sym] = pos
            else:
                self.state["positions"].pop(sym, None)
            stamp = self._stamp()
            rec = {"id": uuid.uuid4().hex[:12], "client_id": order.get("client_order_id"),
                   "symbol": sym, "side": side, "qty": None if qty is None else str(qty),
                   "notional": None if notional is None else str(notional), "type": "market",
                   "tif": order.get("time_in_force", "day"), "status": "filled",
                   "filled_qty": q, "filled_avg_price": fill, "created_at": stamp,
                   "filled_at": stamp, "note": order.get("why")}
            self.state["orders"].append(rec)
            self.state["orders"] = self.state["orders"][-2000:]
            self._save()
            return Order(**rec)

    def cancel_all(self):
        return 0  # every simulated order fills at once

    def close_all(self):
        out = []
        for p in self.positions():
            out.append(self.submit({"symbol": p.symbol, "side": "sell", "qty": str(p.qty),
                                    "type": "market", "time_in_force": "day",
                                    "why": "tümünü kapat"}, price=p.price))
        return out


def _num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        raise BrokerError("Sayı değil: %r" % (x,))
