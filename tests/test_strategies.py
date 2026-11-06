"""The research-based strategy families: turn of the month, Faber GTAA, time
series momentum, risk parity and the strategy blend. Look-ahead and weight
validity are checked for every strategy in test_backtest.py."""

import numpy as np
import pytest

from traderbot import strategies as st
from traderbot.backtest import Panel


def business_panel(closes, start="2020-01-02"):
    syms = list(closes)
    T = len(next(iter(closes.values())))
    days = np.busday_offset(np.datetime64(start, "D"), np.arange(T), roll="forward")
    C = np.column_stack([np.asarray(closes[s], float) for s in syms])
    return Panel(days, syms, C.copy(), C.copy(), C.copy(), C, np.ones_like(C))


def window_on(days, before=1, after=3):
    d = np.array(days, dtype="datetime64[D]")
    return dict(zip(days, st.turn_of_month(d, before, after)))


def test_turn_of_month_uses_the_nyse_calendar():
    # October 2026 ends on Friday the 30th; November starts Monday the 2nd
    w = window_on(["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03",
                   "2026-11-04"])
    # a row is "on" when the NEXT session is in the window (orders fill at the next open)
    assert w == {"2026-10-28": False, "2026-10-29": True, "2026-10-30": True,
                 "2026-11-02": True, "2026-11-03": True, "2026-11-04": False}


def test_turn_of_month_skips_holidays():
    # 1 January 2026 is a holiday: the first sessions are Jan 2, 5 and 6
    w = window_on(["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05",
                   "2026-01-06"])
    assert w == {"2025-12-29": False, "2025-12-30": True, "2025-12-31": True,
                 "2026-01-02": True, "2026-01-05": True, "2026-01-06": False}
    wide = window_on(["2025-12-26", "2025-12-29"], before=3)
    assert wide == {"2025-12-26": True, "2025-12-29": True}   # Dec 29, 30, 31


def test_turn_of_month_strategy_parks_in_bil_between_windows():
    p = business_panel({"SPY": np.linspace(100, 110, 60), "BIL": np.full(60, 50.0)})
    W = st.TurnOfMonth().weights(p)
    on = st.turn_of_month(p.dates, 1, 3)
    assert np.allclose(W[:, 0], on) and np.allclose(W[:, 1], 1 - on)
    assert 0.1 < on.mean() < 0.3          # about 4 of 21 sessions


def trending(n, drift, vol, seed):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


def test_gtaa_moves_assets_below_their_10_month_average_to_bil():
    n = 330
    closes = {s: trending(n, 0.002, 0.005, i) for i, s in enumerate(st.FABER_UNIVERSE)}
    closes["DBC"] = trending(n, -0.003, 0.005, 9)       # falling all the way
    closes["BIL"] = np.linspace(50, 51, n)
    p = business_panel(closes)
    W = st.Gtaa().weights(p)
    last = W[-1]
    assert np.allclose(last[:5], [0.2, 0.2, 0.2, 0.0, 0.2])
    assert np.isclose(last[5], 0.2)
    ready = np.nonzero(np.all(np.isfinite(W), axis=1))[0]
    assert ready[0] > 9 * 19                             # 10 month-end closes first


def test_tsmom_weights_rising_assets_by_inverse_volatility():
    n = 400
    closes = {"A": trending(n, 0.002, 0.004, 1), "B": trending(n, 0.002, 0.012, 2),
              "C": trending(n, -0.003, 0.006, 3), "BIL": np.linspace(50, 51, n)}
    p = business_panel(closes)
    s = st.TimeSeriesMomentum(universe=["A", "B", "C"], lookback=126, vol_n=63, min_assets=2)
    W = s.weights(p)
    last = W[-1]
    assert last[2] == 0.0                                 # C fell: its share waits in BIL
    assert last[0] > 2 * last[1]                          # A is ~3x calmer than B
    assert np.isclose(last.sum(), 1.0) and last[3] > 0.1


def test_risk_parity_is_inverse_volatility_and_fully_invested():
    n = 300
    closes = {"A": trending(n, 0.0005, 0.005, 4), "B": trending(n, 0.0005, 0.015, 5),
              "C": trending(n, 0.0005, 0.010, 6)}
    p = business_panel(closes)
    W = st.RiskParity(universe=["A", "B", "C"], vol_n=63, min_assets=3).weights(p)
    last = W[-1]
    assert np.isclose(last.sum(), 1.0)
    assert last[0] > last[2] > last[1]


def test_inverse_vol_ignores_missing_assets():
    w = st.inverse_vol([0.1, np.nan, 0.2, 0.0])
    assert np.allclose(w, [2 / 3, 0, 1 / 3, 0])
    assert st.inverse_vol([np.nan, np.nan]).sum() == 0


def test_ensemble_blends_members_by_share():
    n = 330
    closes = {s: trending(n, 0.001, 0.008, i) for i, s in enumerate(st.FABER_UNIVERSE)}
    closes["BIL"] = np.linspace(50, 51, n)
    p = business_panel(closes)
    ens = st.Ensemble(parts={"VOL_TARGET": 3, "gtaa": 1})     # keys from the UI come uppercased
    assert ens.p["parts"] == {"vol_target": 0.75, "gtaa": 0.25}
    assert ens.trade_on_change is False                         # vol_target trades on drift
    W = ens.weights(p)
    vt, gt = st.VolTargetTrend().weights(p), st.Gtaa().weights(p)
    ok = np.all(np.isfinite(W), axis=1)
    assert ok.any() and np.array_equal(ok, np.all(np.isfinite(vt), axis=1) &
                                       np.all(np.isfinite(gt), axis=1))
    syms = ens.symbols()
    t = np.nonzero(ok)[0][-1]
    spy = 0.75 * vt[t, 0] + 0.25 * gt[t, 0]
    bil = 0.75 * vt[t, 1] + 0.25 * gt[t, 5]
    assert np.isclose(W[t, syms.index("SPY")], spy) and np.isclose(W[t, syms.index("BIL")], bil)
    assert np.isclose(W[t].sum(), 1.0)


@pytest.mark.parametrize("parts", [{}, {"ensemble": 1}, {"nope": 1}, {"vol_target": 0}])
def test_ensemble_rejects_bad_parts(parts):
    with pytest.raises(ValueError):
        st.Ensemble(parts=parts)
