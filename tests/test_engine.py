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


def test_kill_switch_halts_on_daily_loss(env):
    eng, broker, data, settings, events = env
    eng.start()
    eng.tick()                      # invests, records the day's starting equity
    data.bump = {"SPY": 0.85, "BIL": 1.0}
    eng.state["last_run_date"] = None
    r = eng.tick()
    st = eng.snapshot()
    assert st["halted"] and "Günlük zarar" in st["halt_reason"]
    assert r["ran"] is False
    eng.resume()
    assert not eng.snapshot()["halted"]


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
