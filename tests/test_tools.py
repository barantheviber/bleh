"""Position sizing, alerts and the screener."""

import datetime as dt

import numpy as np
import pytest

from traderbot import alerts, screener, sizing
from traderbot.backtest import Trade, trade_stats
from traderbot.data.bars import Bars
from traderbot.data.yahoo import DataError


# ---------------------------------------------------------------- sizing

def test_fixed_fractional_risks_exactly_the_chosen_share():
    out = sizing.fixed_fractional(10000, 1.0, entry=50.0, stop=48.0)
    assert np.isclose(out["shares"], 50.0)            # $100 risk / $2 per share
    assert np.isclose(out["risk_usd"], 100.0) and np.isclose(out["value"], 2500.0)
    assert out["targets"] == {1: 52.0, 2: 54.0, 3: 56.0} and not out["capped"]


def test_fixed_fractional_is_capped_and_can_round_down():
    out = sizing.fixed_fractional(10000, 2.0, entry=100.0, stop=99.5, max_position_pct=25)
    assert out["capped"] and np.isclose(out["value"], 2500.0)
    whole = sizing.fixed_fractional(10000, 1.0, entry=30.0, stop=27.0, fractional=False)
    assert whole["shares"] == 33                        # 33.33 shares rounded down


@pytest.mark.parametrize("stop", [50.0, 51.0, 0.0])
def test_fixed_fractional_rejects_a_stop_at_or_above_entry(stop):
    with pytest.raises(sizing.SizingError):
        sizing.fixed_fractional(10000, 1.0, entry=50.0, stop=stop)


def test_atr_stop_and_losing_streak():
    assert sizing.atr_stop(100.0, 2.5, 2.0) == 95.0
    assert np.isclose(sizing.losing_streak(1.0, 10), 0.99 ** 10 - 1)   # about -9.6%
    assert np.isclose(sizing.losing_streak(5.0, 10), 0.95 ** 10 - 1)   # about -40%


def test_kelly_and_expectancy():
    assert np.isclose(sizing.kelly(0.5, 2.0), 0.25)
    assert sizing.kelly(0.4, 1.0) < 0                  # a losing system: do not trade it
    assert np.isclose(sizing.expectancy(0.5, 2.0, 1.0), 0.5)
    with pytest.raises(sizing.SizingError):
        sizing.kelly(0.5, 0)


def test_vol_target_weight_matches_the_bot_rule():
    assert np.isclose(sizing.vol_target_weight(0.30, 0.15), 0.5)
    assert sizing.vol_target_weight(0.10, 0.15) == 1.0


def test_trade_stats_payoff_and_profit_factor():
    trades = [Trade("d1", "A", "buy", 10, 10, 100, 0), Trade("d2", "A", "sell", 10, 13, 130, 0),
              Trade("d3", "A", "buy", 10, 10, 100, 0), Trade("d4", "A", "sell", 10, 9, 90, 0)]
    s = trade_stats(trades, [100, 100], 1.0)
    assert np.isclose(s["avg_win"], 0.3) and np.isclose(s["avg_loss"], 0.1)
    assert np.isclose(s["payoff"], 3.0) and np.isclose(s["profit_factor"], 3.0)
    assert np.isclose(s["realized"], 20.0)


# ---------------------------------------------------------------- alerts

def daily_bars(closes, sym="SPY", highs=None, lows=None):
    n = len(closes)
    start = np.datetime64("2025-01-02", "D")
    days = np.busday_offset(start, np.arange(n), roll="forward")
    t = (days.astype("datetime64[s]").astype("int64") + 14 * 3600 + 30 * 60)
    c = np.asarray(closes, float)
    h = c * 1.01 if highs is None else np.asarray(highs, float)
    lo = c * 0.99 if lows is None else np.asarray(lows, float)
    return Bars(sym, "1d", t, c, h, lo, c, np.full(n, 1000.0), c, -14400)


def test_alert_fires_on_the_crossing_only_once():
    a = alerts.new_alert("spy", "price_above", 105)
    bars = daily_bars(np.linspace(90, 110, 50))
    for price, fires in ((100, False), (104, False), (106, True), (107, False)):
        state, _ = alerts.condition(a, bars, price=price, prev_close=100)
        assert alerts.update(a, state, dt.datetime(2026, 1, 1)) is fires
    assert a["enabled"] is False and a["triggered_at"].startswith("2026-01-01")


def test_a_repeating_alert_fires_again_after_resetting():
    a = alerts.new_alert("SPY", "price_below", 95, once=False)
    bars = daily_bars(np.full(30, 100.0))
    seq = [100, 94, 93, 99, 94]
    fired = [alerts.update(a, alerts.condition(a, bars, price=p)[0]) for p in seq]
    assert fired == [False, True, False, False, True] and a["enabled"]


def test_the_first_check_only_records_the_state():
    a = alerts.new_alert("SPY", "price_above", 50)
    assert alerts.update(a, True) is False and a["last_state"] is True


def test_indicator_alert_conditions():
    rising = daily_bars(np.linspace(50, 100, 260))
    sma = alerts.new_alert("SPY", "sma_up", 200)
    assert alerts.condition(sma, rising)[0] is True
    rsi = alerts.new_alert("SPY", "rsi_above", 70)
    assert alerts.condition(rsi, rising)[0] is True
    high = alerts.new_alert("SPY", "high_52w")
    closes = np.r_[np.full(259, 100.0), 103.0]
    assert alerts.condition(high, daily_bars(closes))[0] is True      # 103 > previous high 101
    down = alerts.new_alert("SPY", "change_down", 2)
    assert alerts.condition(down, rising, price=97, prev_close=100)[0] is True
    short = alerts.new_alert("SPY", "rsi_below", 30)
    assert alerts.condition(short, daily_bars([100, 101]))[0] is None   # too little data


@pytest.mark.parametrize("kind,value", [("nope", 1), ("price_above", None), ("price_above", -5),
                                        ("sma_up", 1), ("rsi_above", 150)])
def test_bad_alerts_are_rejected(kind, value):
    with pytest.raises(alerts.AlertError):
        alerts.new_alert("SPY", kind, value)


def test_describe_alerts():
    assert alerts.describe(alerts.new_alert("SPY", "price_above", 600)) == "SPY: fiyat ≥ 600.00"
    assert "200 günlük" in alerts.describe(alerts.new_alert("SPY", "sma_down", 200))


# ---------------------------------------------------------------- screener

def test_measure_momentum_skips_the_last_month():
    c = np.r_[np.full(240, 100.0), np.linspace(100, 150, 60)]
    m = screener.measure(daily_bars(c))
    # 12-1: from 253 bars back (100) to 22 bars back
    assert np.isclose(m["mom_12_1"], c[-22] / c[-253] - 1)
    assert m["trend"] > 0 and m["from_high"] <= 0 and m["vol"] is not None
    assert m["mom_6"] is not None and m["pullback"] is False


def test_pullback_flag_in_an_uptrend():
    c = np.r_[np.linspace(50, 100, 260), [99, 97, 95]]
    m = screener.measure(daily_bars(c))
    assert m["trend"] > 0 and m["rsi2"] < 10 and m["pullback"] is True


def test_score_ranks_momentum_and_closeness_to_the_high():
    rows = [{"mom_12_1": 0.3, "from_high": -0.01}, {"mom_12_1": -0.1, "from_high": -0.3},
            {"mom_12_1": 0.1, "from_high": -0.05}, {"mom_12_1": None, "from_high": -0.1}]
    screener.score(rows)
    assert rows[0]["score"] == 100 and rows[1]["score"] == 0 and rows[2]["score"] == 50
    assert rows[3]["score"] is None


class FakeData(object):
    def __init__(self, series):
        self.series = series

    def bars(self, symbol, interval="1d", range_=None, fresh=False):
        if symbol not in self.series:
            raise DataError("bulunamadı")
        return daily_bars(self.series[symbol], symbol), {}


def test_screen_fetches_in_parallel_and_reports_failures():
    up = np.linspace(50, 100, 300)
    down = np.linspace(100, 60, 300)
    rows, failed = screener.screen(FakeData({"UP": up, "DOWN": down, "TINY": up[:10]}),
                                   ["up", "DOWN", "TINY", "MISSING", "up"])
    assert [r["symbol"] for r in rows] == ["UP", "DOWN"]
    assert set(failed) == {"TINY", "MISSING"}
    assert rows[0]["score"] > rows[1]["score"]


def test_numpy_states_still_fire():
    a = alerts.new_alert("SPY", "sma_up", 20, once=False)
    assert alerts.update(a, np.False_) is False
    assert alerts.update(a, np.True_) is True and a["last_state"] is True
