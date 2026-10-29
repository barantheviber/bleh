"""The bot end to end on real SPY/BIL history, with a simulated broker and a
fixed clock: Wednesday 2026-10-28, 11:00 New York."""

import datetime as dt
import os

import numpy as np
import pytest

from traderbot import config
from traderbot.brokers.sim import SimBroker
from traderbot.data.bars import Bars
from traderbot.data.yahoo import DataError
from traderbot.engine import BotEngine

DATA = os.path.join(os.path.dirname(__file__), "..", "research", "data")
NOW = dt.datetime(2026, 10, 28, 15, 0)  # 11:00 EDT, market open


class FakeData(object):
    """Daily bars from research/data; prices = the last close up to `as_of`."""

    def __init__(self, as_of="2026-10-28", bump=None):
        self.as_of = np.datetime64(as_of)
        self.bump = bump or {}
        self.fail = False

    def daily(self, symbols, range_="3y"):
        if self.fail:
            raise DataError("ağ yok")
        out = {}
        for s in symbols:
            b = Bars.load_csv(os.path.join(DATA, "%s.csv.gz" % s), s, gmtoffset=-14400)
            out[s] = b.take(np.nonzero(b.dates() <= self.as_of)[0])
        return out

    def prices(self, symbols, fresh=False):
        bars = self.daily(symbols)
        return {s: float(bars[s].adjusted().c[-1]) * self.bump.get(s, 1.0) for s in symbols}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADERBOT_HOME", str(tmp_path))
    settings = config.Settings(str(tmp_path / "settings.json"))
    data = FakeData()
    broker = SimBroker(str(tmp_path / "sim.json"), lambda syms: data.prices(syms),
                       start_cash=10000, slippage_bps=0,
                       clock=lambda now=None: {"open": True}, now=lambda: NOW)
    events = []
    eng = BotEngine(settings, broker, data, str(tmp_path / "state.json"),
                    str(tmp_path / "journal.jsonl"), now=lambda: NOW,
                    on_event=lambda k, p: events.append((k, p)), sleep=lambda s: None)
    return eng, broker, data, settings, events


def test_targets_come_from_the_research_winner(env):
    eng, *_ = env
    w, info = eng.targets()
    assert set(w) <= {"SPY", "BIL"} and abs(sum(w.values()) - 100) < 1e-6
    assert info["as_of"] == "2026-10-27"  # yesterday's close, today's bar is still forming


def test_tick_runs_once_and_invests(env):
    eng, broker, *_ , events = env
    eng.start()
    r = eng.tick()
    assert r["ran"] and r["cycle"]["ok"] and r["cycle"]["passed"] >= 1
    acct = broker.account()
    assert acct.cash < 10000 * 0.05  # invested, keeping the 2% buffer
    w, _ = eng.targets()
    pos = {p.symbol: p.market_value / acct.equity * 100 for p in broker.positions()}
    for s, target in w.items():
        assert abs(pos.get(s, 0) - target) < 3.0  # within the band, after the 2% buffer
    again = eng.tick()
    assert again["ran"] is False
    assert any(k == "order" for k, _ in events)


def test_nothing_happens_before_trade_time_or_when_stopped(env):
    eng, broker, data, settings, _ = env
    settings.set("trade_time", "15:30")
    eng.start()
    assert eng.tick()["ran"] is False
    settings.set("trade_time", "10:00")
    eng.stop()
    assert eng.tick()["ran"] is False and broker.positions() == []


def test_approval_mode_waits_for_yes(env):
    eng, broker, data, settings, _ = env
    settings.set("auto_trade", False)
    eng.start()
    eng.tick()
    pending = eng.snapshot()["pending"]
    assert pending and broker.positions() == []
    for p in pending:
        eng.approve(p["fingerprint"])
    assert broker.positions() and eng.snapshot()["pending"] == []


def test_kill_switch_trips_into_sells_only(env):
    eng, broker, data, settings, events = env
    eng.start()
    eng.tick()                      # invests, records the day's starting equity
    data.bump = {"SPY": 0.85, "BIL": 1.0}
    eng.state["last_run_date"] = None
    eng.tick()
    st = eng.snapshot()
    assert st["halted"] and st["halt_kind"] == "auto" and "Günlük zarar" in st["halt_reason"]
    assert eng.sells_only() and not eng.manually_halted()
    assert not any(o.side == "buy" for o in broker.orders()[:-1])  # only the first buy ever
    eng.resume()
    assert not eng.snapshot()["halted"] and not eng.sells_only()


def test_sells_only_mode_sells_but_holds_back_buys(env):
    eng, broker, data, settings, events = env
    eng.start()
    eng.tick()
    assert {p.symbol for p in broker.positions()} == {"SPY"}
    eng.halt("test", kind="auto")
    settings.set("strategy", {"key": "fixed_weights", "params": {"weights": {"BIL": 1.0}}})
    cyc = eng.run_cycle()
    assert cyc["ok"] and cyc["sells_only"]
    assert any(b["symbol"] == "BIL" and b["verdict"] == "HOLD" for b in cyc["blocked"])
    assert broker.positions() == []          # SPY sold, BIL buy held back
    assert broker.account().cash > 9000


def test_manual_halt_blocks_run_now_and_approvals(env):
    eng, broker, data, settings, _ = env
    settings.set("auto_trade", False)
    eng.start()
    eng.tick()
    pending = eng.snapshot()["pending"]
    eng.halt("kullanıcı")
    assert eng.run_cycle()["ok"] is False
    assert eng.run_cycle(dry_run=True)["ok"] is True
    assert eng.snapshot()["pending"] == []
    from traderbot.engine import EngineError
    with pytest.raises(EngineError):
        eng.approve(pending[0]["fingerprint"])
    assert broker.positions() == []


def test_risk_check_blocks_a_blocked_ticker(env):
    eng, broker, data, settings, _ = env
    risk = settings.get("risk")
    risk["blocked"] = ["SPY"]
    settings.set("risk", risk)
    eng.start()
    cyc = eng.run_cycle()
    assert any(b["symbol"] == "SPY" for b in cyc["blocked"])
    assert "SPY" not in {p.symbol for p in broker.positions()}


def test_dry_run_places_nothing(env):
    eng, broker, *_ = env
    cyc = eng.run_cycle(dry_run=True)
    assert cyc["ok"] and cyc["orders"] and broker.positions() == []
    assert eng.snapshot()["last_run_date"] is None


def test_data_failure_is_reported_not_raised(env):
    eng, broker, data, settings, events = env
    data.fail = True
    eng.start()
    r = eng.tick()
    assert r["cycle"]["ok"] is False and broker.positions() == []
    assert any(k == "error" for k, _ in events)


def test_stale_data_is_refused(env):
    eng, broker, data, *_ = env
    data.as_of = np.datetime64("2026-10-20")
    cyc = eng.run_cycle()
    assert cyc["ok"] is False and "güncel değil" in cyc["error"]


def test_close_all_sells_and_halts(env):
    eng, broker, *_ = env
    eng.start()
    eng.tick()
    eng.close_all()
    assert broker.positions() == [] and eng.snapshot()["halted"]


def test_state_survives_restart(env, tmp_path):
    eng, broker, data, settings, _ = env
    eng.start()
    eng.tick()
    again = BotEngine(settings, broker, data, str(tmp_path / "state.json"),
                      str(tmp_path / "journal.jsonl"), now=lambda: NOW)
    assert again.snapshot()["last_run_date"] == "2026-10-28"
    assert again.tick()["ran"] is False


def test_cycle_lock_prevents_a_second_concurrent_cycle(env):
    eng, broker, *_ = env
    eng.cycle_timeout = 0.05
    eng._cycle.acquire()
    try:
        res = eng.run_cycle()
    finally:
        eng._cycle.release()
    assert res["ok"] is False and "başka bir işlem" in res["error"]
    assert broker.positions() == []


def test_repeated_errors_are_journaled_once(env):
    eng, broker, data, settings, events = env
    eng._journal("error", message="Hesap okunamadı: ağ yok")
    eng._journal("error", message="Hesap okunamadı: ağ yok")
    eng._journal("error", message="başka bir hata")
    errors = [p["message"] for k, p in events if k == "error"]
    assert errors == ["Hesap okunamadı: ağ yok", "başka bir hata"]


def test_full_exit_sends_the_exact_quantity_held(env):
    eng, broker, *_ = env
    broker.submit({"symbol": "SPY", "side": "buy", "qty": "12.68926", "type": "market"})
    # trader-rebalance formats shares to 4 decimals: 12.6893 is more than is held
    o = eng._exact_sell({"symbol": "SPY", "side": "sell", "qty": "12.6893", "type": "market"})
    assert o["qty"] == "12.68926"
    eng.execute([o], "2026-10-28")
    assert broker.positions() == []
    partial = eng._exact_sell({"symbol": "SPY", "side": "sell", "qty": "5", "type": "market"})
    assert partial["qty"] == "5"
