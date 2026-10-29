"""Alpaca Trading API v2 (https://docs.alpaca.markets/reference), paper or live.

Keys go in the request headers only. Paper is
https://paper-api.alpaca.markets, live is https://api.alpaca.markets; the
account's own flag decides which, and live needs an explicit opt-in in the
settings (see brokers.create).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .base import Account, Broker, BrokerError, Order, Position

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"


def _default_open(req, timeout):
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, body


class AlpacaBroker(Broker):
    name = "Alpaca"

    def __init__(self, key_id, secret, paper=True, base_url=None, timeout=20, opener=None):
        if not key_id or not secret:
            raise BrokerError("Alpaca anahtarları eksik")
        self.key_id, self.secret = key_id, secret
        self.paper = bool(paper)
        self.base = (base_url or (PAPER if self.paper else LIVE)).rstrip("/")
        self.timeout = timeout
        self.opener = opener or _default_open

    # ------------------------------------------------------------ transport

    def _req(self, method, path, body=None, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "APCA-API-KEY-ID": self.key_id, "APCA-API-SECRET-KEY": self.secret,
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "TraderBot/1.0"})
        try:
            status, raw = self.opener(req, self.timeout)
        except urllib.error.HTTPError as exc:
            msg = _message(exc)
            if exc.code in (401, 403):
                raise BrokerError("Alpaca anahtarı reddedildi (%s): %s. Paper/canlı seçimi "
                                  "anahtarla uyuşuyor mu?" % (exc.code, msg))
            if exc.code == 422:
                raise BrokerError("Alpaca emri reddetti: %s" % msg)
            if exc.code == 429:
                raise BrokerError("Alpaca istek sınırı aşıldı, biraz sonra tekrar deneyin")
            raise BrokerError("Alpaca HTTP %s: %s" % (exc.code, msg))
        except urllib.error.URLError as exc:
            raise BrokerError("Alpaca'ya ulaşılamadı: %s" % (exc.reason,))
        except OSError as exc:
            raise BrokerError("Alpaca bağlantı hatası: %s" % exc)
        if status == 204 or not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise BrokerError("Alpaca yanıtı okunamadı")

    # ------------------------------------------------------------ queries

    def account(self):
        a = self._req("GET", "/v2/account")
        if a.get("trading_blocked") or a.get("account_blocked"):
            status = "BLOCKED"
        else:
            status = a.get("status", "")
        return Account(a.get("cash", 0), a.get("equity") or a.get("portfolio_value") or 0,
                       a.get("buying_power"), a.get("currency", "USD"), self.paper, status,
                       self.label)

    def positions(self):
        out = []
        for p in self._req("GET", "/v2/positions") or []:
            out.append(Position(p["symbol"], p["qty"], p.get("avg_entry_price") or 0,
                                p.get("current_price")))
        return out

    def orders(self, limit=100):
        rows = self._req("GET", "/v2/orders", params={"status": "all", "limit": limit,
                                                      "direction": "desc"}) or []
        return [_order(r) for r in rows]

    def get_order(self, order_id):
        return _order(self._req("GET", "/v2/orders/" + urllib.parse.quote(order_id)))

    def is_open(self):
        return bool((self._req("GET", "/v2/clock") or {}).get("is_open"))

    # ------------------------------------------------------------ trading

    def submit(self, order):
        body = {"symbol": str(order["symbol"]).upper(), "side": order["side"],
                "type": order.get("type", "market"),
                "time_in_force": order.get("time_in_force", "day"),
                "client_order_id": order.get("client_order_id") or "tb-" + uuid.uuid4().hex[:20]}
        for k in ("qty", "notional", "limit_price", "stop_price"):
            if order.get(k) is not None:
                body[k] = str(order[k])
        return _order(self._req("POST", "/v2/orders", body=body))

    def cancel_all(self):
        res = self._req("DELETE", "/v2/orders") or []
        return len(res)

    def close_all(self):
        res = self._req("DELETE", "/v2/positions", params={"cancel_orders": "true"}) or []
        return [_order(r["body"]) for r in res if isinstance(r, dict) and r.get("body")]


def _order(r):
    r = r or {}
    return Order(id=r.get("id"), client_id=r.get("client_order_id"), symbol=r.get("symbol"),
                 side=r.get("side"), qty=r.get("qty"), notional=r.get("notional"),
                 type=r.get("type") or r.get("order_type"), tif=r.get("time_in_force"),
                 status=r.get("status"), filled_qty=r.get("filled_qty") or 0,
                 filled_avg_price=_f(r.get("filled_avg_price")),
                 created_at=r.get("created_at") or r.get("submitted_at"),
                 filled_at=r.get("filled_at"), note=None)


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _message(exc):
    try:
        data = json.loads(exc.read().decode("utf-8"))
        return data.get("message") or str(data)
    except Exception:
        return exc.reason if hasattr(exc, "reason") else str(exc)
