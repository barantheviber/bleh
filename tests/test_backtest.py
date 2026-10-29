import numpy as np
import pytest

from traderbot import strategies as st
from traderbot.backtest import Panel, metrics, run_backtest, trade_stats, Trade
from traderbot.data.bars import Bars
from traderbot.backtest import build_panel


def panel_from(closes, opens=None, start="2020-01-01"):
    """Panel from {sym: closes}; opens default to the closes."""
    syms = list(closes)
    T = len(next(iter(closes.values())))
    dates = np.arange(np.datetime64(start, "D"), np.datetime64(start, "D") + np.timedelta64(T, "D"))
    C = np.column_stack([np.asarray(closes[s], float) for s in syms])
    O = C.copy() if opens is None else np.column_stack([np.asarray(opens[s], float) for s in syms])
    return Panel(dates, syms, O, C.copy(), C.copy(), C, np.ones_like(C))


def test_fills_at_next_open_and_marks_at_close():
    p = panel_from({"A": [10, 11, 12, 13]}, {"A": [10, 10.5, 11.5, 12.5]})
    W = np.ones((4, 1))
    r = run_backtest(p, W, ["A"], capital=1000, cost_bps=0)
    # day 0: cash; day 1: buys 1000/10.5 units at the open, marked at 11
    assert r.equity[0] == 1000
    assert np.isclose(r.equity[1], 1000 / 10.5 * 11)
    assert np.isclose(r.equity[3], 1000 / 10.5 * 13)
    assert len(r.trades) == 1 and r.trades[0].date == "2020-01-02" and r.trades[0].price == 10.5


def test_costs_come_out_of_the_investment():
    p = panel_from({"A": [10, 10, 10]})
    r = run_backtest(p, np.ones((3, 1)), ["A"], capital=1000, cost_bps=10)
    # 1000 = invested * (1 + 0.001) -> invested = 999.000999
    assert np.isclose(r.equity[1], 1000 / 1.001, rtol=1e-9)
    assert np.isclose(r.trades[0].cost, 0.001 * r.trades[0].value)


def test_switches_between_assets_on_signal_change():
    p = panel_from({"A": [10, 10, 20, 20, 20], "B": [5, 5, 5, 10, 10]})
    W = np.array([[1, 0], [1, 0], [0, 1], [0, 1], [0, 1]], float)
    r = run_backtest(p, W, ["A", "B"], capital=100, cost_bps=0)
    # buys A at open of day 1 (10), A doubles on day 2 (200); the switch decided at
    # day 2's close fills at day 3's open, where B is already 10
    assert np.isclose(r.equity[2], 200)
    sides = [(t.date, t.symbol, t.side) for t in r.trades]
    assert sides == [("2020-01-02", "A", "buy"), ("2020-01-04", "A", "sell"),
                     ("2020-01-04", "B", "buy")]
    assert np.isclose(r.equity[4], 200)


def test_no_trade_without_change_or_drift():
    p = panel_from({"A": [10, 11, 12, 13, 14], "B": [10, 10, 10, 10, 10]})
    W = np.tile([0.5, 0.5], (5, 1))
    r = run_backtest(p, W, ["A", "B"], cost_bps=0, band=0.05)
    # A rises 27% while B is flat: weight drifts to ~0.56 -> past the 5 point band
    assert len(r.trades) >= 2
    r2 = run_backtest(p, W, ["A", "B"], cost_bps=0, band=0.5)
    assert len(r2.trades) == 2  # only the opening buys


def test_nan_rows_keep_cash_and_signals_before_start_are_ignored():
    p = panel_from({"A": [10, 10, 10, 10]})
    W = np.array([[np.nan], [np.nan], [1.0], [1.0]])
    r = run_backtest(p, W, ["A"], capital=50, cost_bps=0)
    assert r.trades[0].date == "2020-01-04"
    r = run_backtest(p, np.ones((4, 1)), ["A"], start="2020-01-03", capital=50, cost_bps=0)
    assert r.trades[0].date == "2020-01-04" and np.isnan(r.equity[0])


def test_weights_above_one_are_scaled_down():
    p = panel_from({"A": [10, 10, 10], "B": [10, 10, 10]})
    r = run_backtest(p, np.ones((3, 2)), ["A", "B"], capital=100, cost_bps=0)
    assert np.isclose(sum(t.value for t in r.trades), 100)


def test_metrics_known_series():
    dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-01-01") + np.timedelta64(4, "D"))
    m = metrics([100, 120, 90, 135], dates)
    assert np.isclose(m["total_return"], 0.35)
    assert np.isclose(m["max_dd"], -0.25)
    assert m["dd_peak"] == "2020-01-02" and m["dd_trough"] == "2020-01-03"


def test_trade_stats_round_trips():
    trades = [Trade("d1", "A", "buy", 10, 10, 100, 0), Trade("d2", "A", "sell", 10, 12, 120, 0),
              Trade("d3", "A", "buy", 10, 10, 100, 0), Trade("d4", "A", "sell", 10, 9, 90, 0)]
    s = trade_stats(trades, [100, 100], 1.0)
    assert s["round_trips"] == 2 and s["win_rate"] == 0.5
    assert np.isclose(s["avg_trip"], (0.2 - 0.1) / 2)


def random_panel(symbols, T=900, seed=7, start="2015-01-01"):
    rng = np.random.default_rng(seed)
    closes = {s: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, T))) for s in symbols}
    # business days only, so month ends behave like a trading calendar
    days = np.busday_offset(np.datetime64(start, "D"), np.arange(T), roll="forward")
    syms = list(closes)
    C = np.column_stack([closes[s] for s in syms])
    O = C * (1 + rng.normal(0, 0.002, C.shape))
    return Panel(days, syms, O, np.maximum(O, C) * 1.003, np.minimum(O, C) * 0.997, C,
                 np.ones_like(C))


ALL_SYMBOLS = sorted(set(st.ROTATION_UNIVERSE + st.SECTORS + ["BIL", "AGG", "EFA", "SPY"]))


@pytest.mark.parametrize("key", [k for k in st.REGISTRY if k != "fixed_weights"])
def test_strategy_has_no_look_ahead(key):
    """Weights at row t must be the same whether or not later bars exist.
    The newest row is compared too: without a known next session it is not a
    month end, so it must match the full run only when it truly is not one."""
    p = random_panel(ALL_SYMBOLS)
    strat = st.create(key)
    full = strat.weights(p)
    ends = st.period_ends(p.dates)
    for k in (300, 457, 700, 899):
        sub = Panel(p.dates[:k], p.symbols, p.o[:k], p.h[:k], p.l[:k], p.c[:k], p.v[:k])
        w = strat.weights(sub)
        upto = k if not ends[k - 1] else k - 1
        a, b = w[:upto], full[:upto]
        assert np.array_equal(np.isnan(a), np.isnan(b)), key
        assert np.allclose(np.nan_to_num(a), np.nan_to_num(b)), key


@pytest.mark.parametrize("key", [k for k in st.REGISTRY if k != "fixed_weights"])
def test_strategy_month_end_known_from_next_session(key):
    """Live: on the newest bar, telling the panel the next session's date
    gives the same decision as having the next bar."""
    p = random_panel(ALL_SYMBOLS)
    full = st.create(key).weights(p)
    ends = np.nonzero(st.period_ends(p.dates))[0]
    k = int(ends[ends > 400][0]) + 1  # the newest bar is a month end
    sub = Panel(p.dates[:k], p.symbols, p.o[:k], p.h[:k], p.l[:k], p.c[:k], p.v[:k],
                next_session=p.dates[k])
    w = st.create(key).weights(sub)
    assert np.allclose(np.nan_to_num(w[k - 1]), np.nan_to_num(full[k - 1]))


@pytest.mark.parametrize("key", [k for k in st.REGISTRY if k != "fixed_weights"])
def test_strategy_weights_are_valid(key):
    p = random_panel(ALL_SYMBOLS)
    s = st.create(key)
    W = s.weights(p)
    assert W.shape == (len(p), len(s.symbols()))
    ok = np.all(np.isfinite(W), axis=1)
    assert ok.sum() > 100
    assert np.all(W[ok] >= -1e-12) and np.all(W[ok].sum(axis=1) <= 1 + 1e-9)
    r = run_backtest(p, W, s.symbols(), trade_on_change=s.trade_on_change)
    assert np.isfinite(r.equity[-1]) and r.equity[-1] > 0


def test_sma_trend_holds_off_asset_below_average():
    p = panel_from({"SPY": list(range(1, 11)) + list(range(10, 0, -1)), "BIL": [1.0] * 20})
    W = st.SmaTrend(n=5).weights(p)
    assert np.isnan(W[:4]).all()
    assert list(W[9]) == [1, 0]     # rising: above its 5-day average
    assert list(W[15]) == [0, 1]    # falling: below it, parked in BIL


def test_fixed_weights_normalises():
    p = panel_from({"A": [1, 1], "B": [1, 1]})
    W = st.FixedWeights(weights={"A": 3, "B": 1}).weights(p)
    assert np.allclose(W[0], [0.75, 0.25])


def test_unknown_parameter_rejected():
    with pytest.raises(ValueError):
        st.SmaTrend(lenght=200)


def test_build_panel_ffill_and_calendar():
    def bars(sym, days, closes):
        t = [(np.datetime64(d, "s") - np.datetime64("1970-01-01T00:00:00", "s")).astype(int) + 48600
             for d in days]
        return Bars(sym, "1d", t, closes, closes, closes, closes, [1] * len(closes), closes, -18000)
    spy = bars("SPY", ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [1, 2, 3, 4])
    new = bars("NEW", ["2024-01-03", "2024-01-05"], [10, 30])  # gap on 01-04
    p = build_panel({"SPY": spy, "NEW": new}, calendar_symbol="SPY")
    assert [str(d) for d in p.dates] == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    c = p.close("NEW")
    assert np.isnan(c[0]) and c[1] == 10 and c[2] == 10 and c[3] == 30
    assert p.first_valid("NEW") == 1
