import datetime as dt
from statistics import NormalDist

import numpy as np

from traderbot import events, regime
from traderbot.backtest import Panel


def test_recession_probability_follows_the_ny_fed_probit():
    n = NormalDist()
    assert np.isclose(regime.recession_probability(0.0), n.cdf(-0.5333))
    assert np.isclose(regime.recession_probability(-1.0), n.cdf(-0.5333 + 0.6330))
    assert regime.recession_probability(2.0) < 0.05 < regime.recession_probability(-0.5)
    assert regime.recession_probability(float("nan")) is None


def test_states_by_threshold():
    s = regime._states([0.05, 0.12, 0.19, 0.25, np.nan], [0.12, 0.20])
    assert list(s) == [0, 1, 1, 2, -1]


def make_panel(T=700, seed=1, crash_at=500):
    """SPY rises, then falls hard from `crash_at`; the other series follow simple rules."""
    rng = np.random.default_rng(seed)
    drift = np.where(np.arange(T) < crash_at, 0.0008, -0.004)
    spy = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.008, T)))
    cols = {"SPY": spy, "BIL": 50 * np.exp(np.cumsum(np.full(T, 0.0001))),
            "^VIX": np.where(np.arange(T) < crash_at, 14.0, 32.0),
            "^VIX3M": np.full(T, 20.0),
            "^TNX": np.full(T, 4.0), "^IRX": np.where(np.arange(T) < crash_at, 3.0, 4.5),
            "HYG": spy ** 0.5, "IEF": np.full(T, 100.0)}
    for i, s in enumerate(regime.SECTORS):
        cols[s] = spy * (1 + 0.01 * i)
    days = np.busday_offset(np.datetime64("2020-01-01", "D"), np.arange(T), roll="forward")
    syms = list(cols)
    C = np.column_stack([cols[s] for s in syms])
    return Panel(days, syms, C, C, C, C, np.ones_like(C))


def test_snapshot_reads_the_latest_state_of_each_indicator():
    p = make_panel()
    snap = regime.snapshot(p)
    rows = {r["key"]: r for r in snap["rows"]}
    assert rows["trend"]["label"] == "Ortalamanın altında" and rows["trend"]["risk_on"] is False
    assert rows["vix"]["state"] == 2 and rows["vix_term"]["label"].startswith("Ters")
    # 10y 4.0% - 3m 4.5% = -0.5 points: inverted, N(-0.5333 + 0.3165) = 41%
    assert rows["curve"]["state"] == 0 and np.isclose(rows["curve"]["value"], -0.5)
    assert np.isclose(rows["curve"]["recession_probability"], NormalDist().cdf(-0.5333 + 0.3165))
    assert rows["breadth"]["label"].startswith("Dar")
    assert snap["available"] == 8 and snap["verdict"] == "Temkinli"


def test_missing_symbols_are_reported_not_guessed():
    p = make_panel()
    keep = ["SPY", "BIL"]
    small = Panel(p.dates, keep, p.o[:, :2], p.h[:, :2], p.l[:, :2], p.c[:, :2], p.v[:, :2])
    snap = regime.snapshot(small)
    rows = {r["key"]: r for r in snap["rows"]}
    assert rows["vix"]["label"] == "veri yok" and rows["vix"]["state"] == -1
    assert snap["available"] == 3          # trend, momentum, realised volatility


def test_forward_returns_and_volatility():
    c = np.array([100, 110, 121, 133.1, 146.41])
    assert np.allclose(regime.forward_returns(c, 2)[:3], 0.21)
    assert np.isnan(regime.forward_returns(c, 2)[3:]).all()
    v = regime.forward_vol(c, 2)
    assert np.allclose(v[:3], 0.0) and np.isnan(v[3:]).all()   # constant 10% steps


def test_conditional_stats_split_the_days_by_state():
    p = make_panel()
    out = regime.conditional_stats(p, horizon=21)
    trend = next(i for i in out["indicators"] if i["key"] == "trend")
    shares = [r["stats"]["share"] for r in trend["rows"] if r["stats"]]
    assert np.isclose(sum(shares), 1.0)
    below, above = trend["rows"]
    assert below["stats"]["mean"] < 0 < above["stats"]["mean"]      # the crash follows
    assert out["all"]["days"] == len(p) - 21          # every day with 21 days ahead


def test_upcoming_events_for_late_october_2026():
    ev = events.upcoming(dt.date(2026, 10, 29), days=60)
    kinds = [(e["date"].isoformat(), e["kind"]) for e in ev]
    assert ("2026-11-26", "holiday") in kinds          # Thanksgiving
    assert ("2026-11-27", "early") in kinds and ("2026-12-24", "early") in kinds
    assert ("2026-12-25", "holiday") in kinds
    assert ("2026-12-09", "fomc") in kinds and ("2026-10-28", "fomc") not in kinds
    toms = [e for e in ev if e["kind"] == "tom"]
    assert toms[0]["date"] == dt.date(2026, 10, 30) and "04.11" in toms[0]["title"]
    assert toms[1]["date"] == dt.date(2026, 11, 30) and "03.12" in toms[1]["title"]
    fomc = next(e for e in ev if e["kind"] == "fomc")
    assert "projeksiyon" in fomc["title"] and "geçici" not in fomc["title"]
    assert [e["date"] for e in ev] == sorted(e["date"] for e in ev)


def test_2027_fomc_dates_are_marked_tentative():
    ev = events.upcoming(dt.date(2027, 1, 1), days=30)
    fomc = [e for e in ev if e["kind"] == "fomc"]
    assert fomc and fomc[0]["date"] == dt.date(2027, 1, 27) and "geçici" in fomc[0]["title"]
