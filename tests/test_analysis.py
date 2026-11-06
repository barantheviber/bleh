import math
from statistics import NormalDist

import numpy as np
import pytest

from traderbot import analysis as an
from traderbot.backtest import Panel

# +2% / -1% alternating: mean 0.5%, population sd 1.5%, skew 0, kurtosis 1
TWO_POINT = np.array([0.02, -0.01] * 10)


def test_moments_of_a_two_point_series():
    sr, skew, kurt = an.moments(TWO_POINT)
    assert np.isclose(sr, 0.005 / np.std(TWO_POINT, ddof=1))
    assert abs(skew) < 1e-12 and np.isclose(kurt, 1.0)


def test_probabilistic_sharpe_by_hand():
    # z = SR * sqrt(T-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) = 0.32489 * sqrt(19) / 1
    assert np.isclose(an.probabilistic_sharpe(TWO_POINT), 0.92164, atol=2e-4)
    sr = an.moments(TWO_POINT)[0]
    assert np.isclose(an.probabilistic_sharpe(TWO_POINT, benchmark=sr), 0.5)
    assert an.probabilistic_sharpe(-TWO_POINT) < 0.1


def test_fat_tails_and_negative_skew_widen_the_sharpe_error():
    base = an._sr_std(0.1, 0.0, 3.0)
    assert an._sr_std(0.1, 0.0, 10.0) > base      # fat tails
    assert an._sr_std(0.1, -1.0, 3.0) > base      # crash risk


def test_expected_max_sharpe_of_56_lucky_trials():
    # the false-strategy factor for 56 trials is about 2.32 standard deviations
    assert np.isclose(an.expected_max_sharpe(56, 1.0), 2.32, atol=0.01)
    assert an.expected_max_sharpe(1, 1.0) == 0.0
    assert an.expected_max_sharpe(10, 0.04) == pytest.approx(0.2 * an.expected_max_sharpe(10, 1.0))


def test_deflated_sharpe_shrinks_with_the_number_of_tries():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0006, 0.01, 1500)
    one, sr0 = an.deflated_sharpe(r, [an.moments(r)[0]])
    assert sr0 == 0.0 and np.isclose(one, an.probabilistic_sharpe(r))
    many = rng.normal(0.0, 0.02, 200).tolist() + [an.moments(r)[0]]
    dsr, sr0 = an.deflated_sharpe(r, many)
    assert sr0 > 0 and dsr < one


def test_min_track_record_by_hand():
    sr = an.moments(TWO_POINT)[0]
    expect = 1 + (NormalDist().inv_cdf(0.95) / sr) ** 2      # skew 0, kurtosis 1
    assert np.isclose(an.min_track_record(TWO_POINT), expect)
    assert an.min_track_record(-TWO_POINT) == math.inf


def test_bootstrap_of_a_constant_return_has_no_spread():
    out = an.bootstrap(np.full(500, 0.001), horizon=252, n_paths=50, seed=1)
    want = 1.001 ** 252 - 1
    assert all(np.isclose(v, want) for v in out["final"].values())
    assert all(v == 0 for v in out["max_dd"].values()) and out["p_loss"] == 0
    assert len(out["fan"][50]) == 252 and np.isclose(out["fan"][50][-1], 1 + want)


def test_bootstrap_is_reproducible_and_ordered():
    r = np.random.default_rng(5).normal(0.0004, 0.012, 2000)
    a = an.bootstrap(r, 252, n_paths=400, seed=9)
    b = an.bootstrap(r, 252, n_paths=400, seed=9)
    assert a["final"] == b["final"]
    f = [a["final"][p] for p in a["percentiles"]]
    assert f == sorted(f) and a["max_dd"][5] <= a["max_dd"][95] <= 0
    assert 0 < a["p_loss"] < 1 and a["p_dd"][0.1] >= a["p_dd"][0.3]


def business_panel(T=1900, seed=11):
    rng = np.random.default_rng(seed)
    days = np.busday_offset(np.datetime64("2015-01-01", "D"), np.arange(T), roll="forward")
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, T)))
    bil = 50 * np.exp(np.cumsum(np.full(T, 0.00005)))
    C = np.column_stack([spy, bil])
    return Panel(days, ["SPY", "BIL"], C.copy(), C * 1.002, C * 0.998, C, np.ones_like(C))


def test_walk_forward_stitches_out_of_sample_windows():
    p = business_panel()
    grid = [{"n": 20}, {"n": 50}, {"n": 100}]
    wf = an.walk_forward("sma_trend", grid, p, start="2015-01-01", train_years=2, test_years=1,
                         capital=1000, cost_bps=0)
    assert len(wf["folds"]) >= 4
    assert all(f["params"] in grid for f in wf["folds"])
    assert wf["equity"][0] == 1000 and np.all(np.isfinite(wf["equity"]))
    assert np.all(np.diff(wf["dates"].astype(int)) > 0)
    first, second = wf["folds"][0], wf["folds"][1]
    assert first["test"][0] >= "2017-01-01" and second["test"][0] > first["test"][1]
    # every test window starts from the cash the previous one ended with
    joins = [i for i in range(1, len(wf["dates"]))
             if wf["dates"][i] > np.datetime64(wf["folds"][0]["test"][1])][:1]
    assert np.isclose(wf["equity"][joins[0]], wf["equity"][joins[0] - 1])


def test_walk_forward_needs_a_test_window():
    with pytest.raises(ValueError):
        an.walk_forward("sma_trend", [{"n": 20}], business_panel(T=300), start="2015-01-01",
                        train_years=5)


def equity_of(r, start=100.0):
    return start * np.r_[1.0, np.cumprod(1 + np.asarray(r))]


def days(n, start="2024-01-01"):
    return np.arange(np.datetime64(start, "D"), np.datetime64(start, "D") + np.timedelta64(n, "D"))


def test_risk_report_tail_measures():
    r = np.linspace(-0.05, 0.05, 101)
    rep = an.risk_report(equity_of(r), days(102))
    assert np.isclose(rep["var95"], -0.045) and np.isclose(rep["var99"], -0.049)
    assert np.isclose(rep["es975"], -0.049)            # mean of -5.0%, -4.9%, -4.8%
    assert np.isclose(rep["worst_day"], -0.05) and np.isclose(rep["best_day"], 0.05)
    assert abs(rep["skew"]) < 1e-6


def test_beta_and_correlation_against_the_benchmark():
    rb = np.random.default_rng(2).normal(0.0, 0.01, 300)
    rep = an.risk_report(equity_of(0.5 * rb), days(301), bench_equity=equity_of(rb))
    assert np.isclose(rep["beta"], 0.5) and np.isclose(rep["correlation"], 1.0)
    assert np.isclose(rep["downside_capture"], 0.5)


def test_ulcer_index_and_longest_drawdown():
    assert np.isclose(an.ulcer_index([100, 90, 100]), math.sqrt(100 / 3))
    eq = [100, 110, 100, 105, 111, 90, 95]
    span, peak, rec = an.longest_drawdown(eq, days(7))
    assert (span, peak, rec) == (3, "2024-01-02", "2024-01-05")
    span, peak, rec = an.longest_drawdown([100, 120, 60, 70], days(4))
    assert (span, peak, rec) == (2, "2024-01-02", None)          # not recovered yet


def test_monthly_returns_table():
    d = np.array(["2026-01-30", "2026-01-31", "2026-02-27", "2026-02-28"], dtype="datetime64[D]")
    table = an.monthly_returns([100, 110, 121, 121], d)
    assert np.isclose(table[2026]["months"][0], 0.10)
    assert np.isclose(table[2026]["months"][1], 0.10)
    assert table[2026]["months"][2] is None and np.isclose(table[2026]["year"], 0.21)


def test_rolling_sharpe_waits_for_a_full_window():
    rs = an.rolling_sharpe(equity_of(np.random.default_rng(1).normal(0.001, 0.01, 400)), 252)
    assert np.isnan(rs[:252]).all() and np.isfinite(rs[252:]).all() and len(rs) == 401
