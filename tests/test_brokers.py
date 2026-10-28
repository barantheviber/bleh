import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from traderbot.brokers import BrokerError
from traderbot.brokers.alpaca import AlpacaBroker
from traderbot.brokers.sim import SimBroker, us_listed

OPEN = lambda now=None: {"open": True}     # noqa: E731
CLOSED = lambda now=None: {"open": False}  # noqa: E731


def make_sim(tmp_path, prices=None, clock=OPEN, slippage=0.0, cash=1000.0):
    prices = prices if prices is not None else {"SPY": 100.0, "BIL": 50.0, "BTC-USD": 60000.0}
    return SimBroker(str(tmp_path / "sim.json"), lambda syms: {s: prices[s] for s in syms if s in prices},
                     start_cash=cash, slippage_bps=slippage, clock=clock,
                     now=lambda: dt.datetime(2026, 10, 28, 15, 0))


def test_sim_buy_notional_then_sell_qty(tmp_path):
    b = make_sim(tmp_path)
    o = b.submit({"symbol": "SPY", "side": "buy", "notional": "500", "type": "market",
                  "time_in_force": "day"})
    assert o.status == "filled" and abs(o.filled_qty - 5) < 1e-9
    acct = b.account()
    assert abs(acct.cash - 500) < 1e-9 and abs(acct.equity - 1000) < 1e-9
    b.submit({"symbol": "SPY", "side": "sell", "qty": "2", "type": "market"})
    pos = b.positions()
    assert len(pos) == 1 and abs(pos[0].qty - 3) < 1e-9 and abs(pos[0].avg_price - 100) < 1e-9
    assert abs(b.account().cash - 700) < 1e-9


def test_sim_slippage_moves_fill_against_you(tmp_path):
    b = make_sim(tmp_path, slippage=10)
    o = b.submit({"symbol": "SPY", "side": "buy", "qty": "1", "type": "market"})
    assert abs(o.filled_avg_price - 100.1) < 1e-9
    o = b.submit({"symbol": "SPY", "side": "sell", "qty": "1", "type": "market"})
    assert abs(o.filled_avg_price - 99.9) < 1e-9


def test_sim_blocks_margin_short_and_bad_orders(tmp_path):
    b = make_sim(tmp_path)
    with pytest.raises(BrokerError, match="Yetersiz nakit"):
        b.submit({"symbol": "SPY", "side": "buy", "qty": "11", "type": "market"})
    with pytest.raises(BrokerError, match="açığa satış"):
        b.submit({"symbol": "SPY", "side": "sell", "qty": "1", "type": "market"})
    with pytest.raises(BrokerError):
        b.submit({"symbol": "SPY", "side": "buy", "qty": "1", "notional": "5"})
    with pytest.raises(BrokerError, match="piyasa emri"):
        b.submit({"symbol": "SPY", "side": "buy", "qty": "1", "type": "limit", "limit_price": "9"})
    assert b.account().cash == 1000


def test_sim_us_orders_need_open_market_crypto_does_not(tmp_path):
    b = make_sim(tmp_path, clock=CLOSED, cash=100000)
    with pytest.raises(BrokerError, match="NYSE kapalı"):
        b.submit({"symbol": "SPY", "side": "buy", "qty": "1", "type": "market"})
    o = b.submit({"symbol": "BTC-USD", "side": "buy", "notional": "600", "type": "market"})
    assert abs(o.filled_qty - 0.01) < 1e-12


def test_sim_persists_and_resets(tmp_path):
    b = make_sim(tmp_path)
    b.submit({"symbol": "SPY", "side": "buy", "qty": "3", "type": "market"})
    again = make_sim(tmp_path)
    assert abs(again.positions()[0].qty - 3) < 1e-9 and len(again.orders()) == 1
    again.reset(5000)
    assert again.account().equity == 5000 and again.positions() == []


def test_sim_close_all_and_portfolio_shape(tmp_path):
    b = make_sim(tmp_path)
    b.submit({"symbol": "SPY", "side": "buy", "qty": "2", "type": "market"})
    b.submit({"symbol": "BIL", "side": "buy", "qty": "4", "type": "market"})
    assert b.portfolio() == {"cash": 600.0, "positions": [{"ticker": "BIL", "shares": 4.0},
                                                          {"ticker": "SPY", "shares": 2.0}]}
    b.close_all()
    assert b.positions() == [] and abs(b.account().cash - 1000) < 1e-9


# ---------------------------------------------------------------- Alpaca

class FakeAlpaca(BaseHTTPRequestHandler):
    calls = []
    account = {"cash": "1000.50", "equity": "1500.25", "buying_power": "2001",
               "currency": "USD", "status": "ACTIVE"}

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        FakeAlpaca.calls.append((self.command, self.path,
                                {k.lower(): v for k, v in self.headers.items()}, body))
        return body

    def do_GET(self):
        self._record()
        if self.headers.get("APCA-API-KEY-ID") != "KEY":
            return self._send(401, {"code": 40110000, "message": "request is not authorized"})
        if self.path == "/v2/account":
            return self._send(200, self.account)
        if self.path == "/v2/positions":
            return self._send(200, [{"symbol": "SPY", "qty": "2.5", "avg_entry_price": "600",
                                     "current_price": "610"}])
        if self.path == "/v2/clock":
            return self._send(200, {"is_open": True})
        if self.path.startswith("/v2/orders"):
            return self._send(200, [{"id": "o1", "symbol": "SPY", "side": "buy",
                                     "status": "filled", "filled_qty": "1",
                                     "filled_avg_price": "605.5"}])
        self._send(404, {"message": "not found"})

    def do_POST(self):
        body = self._record()
        if body.get("symbol") == "BAD":
            return self._send(422, {"code": 42210000, "message": "asset BAD not found"})
        self._send(200, {"id": "o2", "client_order_id": body.get("client_order_id"),
                         "symbol": body["symbol"], "side": body["side"],
                         "notional": body.get("notional"), "qty": body.get("qty"),
                         "type": body["type"], "time_in_force": body["time_in_force"],
                         "status": "accepted", "filled_qty": "0", "filled_avg_price": None})

    def do_DELETE(self):
        self._record()
        if self.path.startswith("/v2/positions"):
            return self._send(207, [{"symbol": "SPY", "status": 200,
                                     "body": {"id": "o3", "symbol": "SPY", "side": "sell",
                                              "status": "accepted"}}])
        self._send(207, [{"id": "o1", "status": 200}])


@pytest.fixture
def alpaca():
    FakeAlpaca.calls = []
    srv = HTTPServer(("127.0.0.1", 0), FakeAlpaca)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def test_alpaca_account_positions_orders(alpaca):
    b = AlpacaBroker("KEY", "SECRET", paper=True, base_url=alpaca)
    a = b.account()
    assert a.cash == 1000.5 and a.equity == 1500.25 and a.buying_power == 2001 and a.paper
    p = b.positions()[0]
    assert p.symbol == "SPY" and p.qty == 2.5 and p.price == 610 and p.unrealized_pl == 25
    assert b.orders()[0].filled_avg_price == 605.5
    assert b.is_open() is True
    method, path, headers, _ = FakeAlpaca.calls[0]
    assert headers["apca-api-key-id"] == "KEY" and headers["apca-api-secret-key"] == "SECRET"
    assert FakeAlpaca.calls[2][1] == "/v2/orders?status=all&limit=100&direction=desc"


def test_alpaca_submit_sends_strings_and_client_id(alpaca):
    b = AlpacaBroker("KEY", "SECRET", base_url=alpaca)
    o = b.submit({"symbol": "spy", "side": "buy", "notional": 1250, "type": "market",
                  "time_in_force": "day"})
    body = FakeAlpaca.calls[-1][3]
    assert body["symbol"] == "SPY" and body["notional"] == "1250" and "qty" not in body
    assert body["client_order_id"].startswith("tb-")
    assert o.status == "accepted" and not o.done


def test_alpaca_errors_are_readable(alpaca):
    with pytest.raises(BrokerError, match="reddetti: asset BAD not found"):
        AlpacaBroker("KEY", "SECRET", base_url=alpaca).submit(
            {"symbol": "BAD", "side": "buy", "qty": "1"})
    with pytest.raises(BrokerError, match="reddedildi"):
        AlpacaBroker("WRONG", "SECRET", base_url=alpaca).account()


def test_alpaca_close_all_and_cancel_all(alpaca):
    b = AlpacaBroker("KEY", "SECRET", base_url=alpaca)
    closed = b.close_all()
    assert closed[0].symbol == "SPY" and closed[0].side == "sell"
    assert FakeAlpaca.calls[-1][1] == "/v2/positions?cancel_orders=true"
    assert b.cancel_all() == 1


def test_alpaca_unreachable():
    with pytest.raises(BrokerError, match="ulaşılamadı"):
        AlpacaBroker("KEY", "SECRET", base_url="http://127.0.0.1:9", timeout=2).account()


def test_alpaca_paper_and_live_urls():
    assert AlpacaBroker("K", "S", paper=True).base == "https://paper-api.alpaca.markets"
    assert AlpacaBroker("K", "S", paper=False).base == "https://api.alpaca.markets"


def test_us_listed():
    for sym in ("SPY", "AAPL", "BRK.B", "BRK-B", "LEN.B"):
        assert us_listed(sym), sym
    for sym in ("THYAO.IS", "BTC-USD", "EURUSD=X", "^GSPC", "BT.L"):
        assert not us_listed(sym), sym
