"""How far to trust a backtest, and how bad it can get.

- probabilistic_sharpe, deflated_sharpe, min_track_record: Bailey and
  López de Prado (2012, 2014). A Sharpe ratio measured on a few years of
  data, or picked as the best of many tries, overstates the real one.
- bootstrap: stationary block bootstrap (Politis and Romano, 1994) of daily
  returns: a range of futures with the same day-to-day behaviour.
- walk_forward: choose parameters on the past, trade them on the next
  stretch, repeat (Pardo). The stitched curve has no hindsight in it.
- risk_report: VaR, expected shortfall, ulcer index, worst stretches, beta.

Sharpe ratios inside this module are per period (daily) unless the name
says annual; annual = daily * sqrt(252).
"""

import datetime as _dt
import math
from statistics import NormalDist

import numpy as np

from . import indicators as ind
from . import strategies
from .backtest import metrics, run_backtest

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def returns(equity):
    """Daily simple returns of an equity curve; NaN days dropped."""
    eq = np.asarray(equity, dtype=np.float64)
    eq = eq[np.isfinite(eq)]
    if len(eq) < 2:
        return np.zeros(0)
    return eq[1:] / eq[:-1] - 1.0


def excess_returns(equity, rf_daily):
    """Daily returns of `equity` minus the cash return of the same days
    (both arrays on one calendar); days without a value are dropped."""
    eq = np.asarray(equity, dtype=np.float64)
    rf = np.nan_to_num(np.asarray(rf_daily, dtype=np.float64))
    ok = np.isfinite(eq)
    eq, rf = eq[ok], rf[ok]
    if len(eq) < 2:
        return np.zeros(0)
    return eq[1:] / eq[:-1] - 1.0 - rf[1:]


def moments(r):
    """(Sharpe per period with ddof=1, skewness, kurtosis) - kurtosis is
    the raw fourth moment, 3 for a normal distribution."""
    r = np.asarray(r, dtype=np.float64)
    if len(r) < 3:
        return 0.0, 0.0, 3.0
    mu, sd = r.mean(), r.std(ddof=1)
    pop = r.std()
    if sd <= 0 or pop <= 0:
        return 0.0, 0.0, 3.0
    z = (r - mu) / pop
    return float(mu / sd), float(np.mean(z ** 3)), float(np.mean(z ** 4))


def _sr_std(sr, skew, kurt):
    """Standard deviation of the Sharpe estimate times sqrt(T-1)."""
    v = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    return math.sqrt(max(v, 1e-12))


def probabilistic_sharpe(r, benchmark=0.0):
    """Probability that the true per-period Sharpe ratio is above `benchmark`,
    given T returns with their skewness and kurtosis (PSR)."""
    r = np.asarray(r, dtype=np.float64)
    if len(r) < 3:
        return float("nan")
    sr, skew, kurt = moments(r)
    z = (sr - benchmark) * math.sqrt(len(r) - 1) / _sr_std(sr, skew, kurt)
    return float(_N.cdf(z))


def expected_max_sharpe(n_trials, variance):
    """Expected best Sharpe ratio among n_trials strategies with no skill,
    whose Sharpe ratios vary with `variance` (the False Strategy Theorem)."""
    n = int(n_trials)
    if n <= 1 or variance <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n)
    b = _N.inv_cdf(1.0 - 1.0 / (n * math.e))
    return float(math.sqrt(variance) * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b))


def deflated_sharpe(r, trial_sharpes):
    """PSR against the best Sharpe that luck alone would give after trying
    every strategy in `trial_sharpes` (per-period Sharpe ratios, this one
    included). One trial gives back PSR(0). Returns (dsr, sr0)."""
    trials = np.asarray([x for x in trial_sharpes if np.isfinite(x)], dtype=np.float64)
    var = float(trials.var(ddof=1)) if len(trials) > 1 else 0.0
    sr0 = expected_max_sharpe(len(trials), var)
    return probabilistic_sharpe(r, sr0), sr0


def min_track_record(r, benchmark=0.0, prob=0.95):
    """Returns needed before the Sharpe ratio beats `benchmark` with
    probability `prob` (minimum track record length, in periods)."""
    sr, skew, kurt = moments(r)
    if sr <= benchmark:
        return float("inf")
    k = _N.inv_cdf(prob) / (sr - benchmark)
    return float(1.0 + _sr_std(sr, skew, kurt) ** 2 * k * k)


# ---------------------------------------------------------------- Monte Carlo

def bootstrap(r, horizon, n_paths=2000, mean_block=21, seed=0):
    """Stationary bootstrap: each path strings together blocks of the past
    returns, of random length (mean `mean_block` days), so streaks and calm
    or wild stretches survive. Returns percentiles of the outcome and the
    fan of equity paths (start = 1)."""
    r = np.asarray(r, dtype=np.float64)
    r = r[np.isfinite(r)]
    T, H = len(r), int(horizon)
    if T < 2 or H < 1:
        raise ValueError("bootstrap: en az 2 günlük getiri ve 1 günlük ufuk gerekli")
    rng = np.random.default_rng(seed)
    idx = np.empty((n_paths, H), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, n_paths)
    jump = rng.random((n_paths, H)) < 1.0 / max(1.0, float(mean_block))
    fresh = rng.integers(0, T, (n_paths, H))
    for h in range(1, H):
        idx[:, h] = np.where(jump[:, h], fresh[:, h], (idx[:, h - 1] + 1) % T)
    eq = np.cumprod(1.0 + r[idx], axis=1)
    final = eq[:, -1] - 1.0
    peak = np.maximum.accumulate(np.maximum(eq, 1.0), axis=1)
    dd = np.min(eq / peak - 1.0, axis=1)
    years = H / ind.TRADING_DAYS
    with np.errstate(invalid="ignore"):
        cagr = np.where(eq[:, -1] > 0, eq[:, -1] ** (1.0 / years) - 1.0, -1.0)
    q = [5, 25, 50, 75, 95]
    fan = np.percentile(eq, q, axis=0)
    return {
        "horizon": H, "paths": n_paths, "mean_block": mean_block, "years": years,
        "percentiles": q,
        "final": dict(zip(q, np.percentile(final, q).tolist())),
        "cagr": dict(zip(q, np.percentile(cagr, q).tolist())),
        "max_dd": dict(zip(q, np.percentile(dd, q).tolist())),
        "p_loss": float(np.mean(final < 0)),
        "p_dd": {lim: float(np.mean(dd <= -lim)) for lim in (0.1, 0.2, 0.3, 0.5)},
        "fan": dict(zip(q, fan)),
    }


# ---------------------------------------------------------------- walk forward

def _plus_years(day, years):
    d = _dt.date.fromisoformat(str(np.datetime64(day, "D")))
    try:
        return np.datetime64(d.replace(year=d.year + years), "D")
    except ValueError:  # 29 February
        return np.datetime64(d.replace(year=d.year + years, day=28), "D")


def walk_forward(key, grid, panel, start, end=None, train_years=5, test_years=1,
                 anchored=False, rf=None, capital=10000.0, cost_bps=5.0, band=0.05,
                 progress=None):
    """Re-choose `key`'s parameters from `grid` on each training window by
    excess Sharpe, then trade them on the following test window. The test
    windows are stitched into one out-of-sample equity curve."""
    if not grid:
        raise ValueError("walk_forward: parametre ızgarası boş")
    strats = [strategies.create(key, **params) for params in grid]
    Ws = [s.weights(panel) for s in strats]
    first = np.datetime64(start, "D")
    last = panel.dates[-1] if end is None else min(np.datetime64(end, "D"), panel.dates[-1])
    folds, eq_dates, eq_vals = [], [], []
    cash = float(capital)
    test_start = _plus_years(first, train_years)
    kw = dict(cost_bps=cost_bps, band=band)
    while test_start <= last:
        test_end = min(_plus_years(test_start, test_years) - np.timedelta64(1, "D"), last)
        train_start = first if anchored else _plus_years(test_start, -train_years)
        train_end = test_start - np.timedelta64(1, "D")
        scores = []
        for s, W in zip(strats, Ws):
            r = run_backtest(panel, W, s.symbols(), train_start, train_end, capital=capital,
                             trade_on_change=s.trade_on_change, **kw)
            scores.append(r.metrics(rf)["sharpe_excess"])
        best = int(np.nanargmax(scores))
        s = strats[best]
        res = run_backtest(panel, Ws[best], s.symbols(), test_start, test_end, capital=cash,
                           trade_on_change=s.trade_on_change, **kw)
        d, eq = res.window()
        ok = np.isfinite(eq)
        if ok.sum() >= 2:
            m = res.metrics(rf)
            folds.append({"train": (str(train_start), str(train_end)),
                          "test": (str(d[ok][0]), str(d[ok][-1])),
                          "params": dict(grid[best]), "train_sharpe": float(scores[best]),
                          "test_return": float(eq[ok][-1] / eq[ok][0] - 1.0),
                          "test_sharpe": float(m["sharpe_excess"]),
                          "test_max_dd": float(m["max_dd"])})
            eq_dates.extend(d[ok])
            eq_vals.extend(eq[ok])
            cash = float(eq[ok][-1])
        if progress:
            progress(len(folds))
        test_start = test_end + np.timedelta64(1, "D")
    if not folds:
        raise ValueError("walk_forward: test penceresi kalmadı (eğitim süresi veriden uzun)")
    dates = np.array(eq_dates, dtype="datetime64[D]")
    equity = np.array(eq_vals, dtype=np.float64)
    is_sh = float(np.mean([f["train_sharpe"] for f in folds]))
    oos = metrics(equity, dates, None if rf is None else _align(rf, panel.dates, dates))
    return {"folds": folds, "dates": dates, "equity": equity, "metrics": oos,
            "train_sharpe": is_sh,
            "efficiency": float(oos["sharpe_excess"] / is_sh) if is_sh > 0 else float("nan")}


def _align(series, src_dates, dates):
    pos = np.searchsorted(src_dates, dates)
    pos = np.clip(pos, 0, len(src_dates) - 1)
    out = np.asarray(series, dtype=np.float64)[pos]
    out[src_dates[pos] != dates] = np.nan
    return out


# ---------------------------------------------------------------- risk

def drawdowns(equity):
    """Drawdown series (0 at a new high, -0.25 at 25% below the peak)."""
    eq = np.asarray(equity, dtype=np.float64)
    return eq / np.maximum.accumulate(eq) - 1.0


def ulcer_index(equity):
    """Peter Martin's ulcer index: root mean square drawdown, in percent. It
    counts how deep and how long the account sat below its high."""
    dd = 100.0 * drawdowns(equity)
    return float(np.sqrt(np.mean(dd * dd))) if len(dd) else 0.0


def longest_drawdown(equity, dates):
    """(days, peak date, recovery date or None) of the longest stretch below
    a previous high, in calendar days."""
    eq = np.asarray(equity, dtype=np.float64)
    d = np.asarray(dates, dtype="datetime64[D]")
    under = drawdowns(eq) < -1e-12
    best, cur_start = (0, None, None), None
    for i in range(len(eq)):
        if under[i] and cur_start is None:
            cur_start = i - 1 if i else 0
        if (not under[i] or i == len(eq) - 1) and cur_start is not None:
            stop = i if not under[i] else None
            span = int((d[i] - d[cur_start]).astype(int))
            if span > best[0]:
                best = (span, str(d[cur_start]), None if stop is None else str(d[stop]))
            cur_start = None
    return best


def risk_report(equity, dates, bench_equity=None):
    """Tail risk and path statistics of a daily equity curve."""
    eq = np.asarray(equity, dtype=np.float64)
    d = np.asarray(dates, dtype="datetime64[D]")
    ok = np.isfinite(eq)
    eq, d = eq[ok], d[ok]
    r = returns(eq)
    out = {"days": int(len(r))}
    if len(r) < 20:
        return out
    var95, var99 = np.percentile(r, 5), np.percentile(r, 1)
    cut = np.percentile(r, 2.5)
    sr, skew, kurt = moments(r)

    def worst(n):
        if len(eq) <= n:
            return None
        return float(np.min(eq[n:] / eq[:-n] - 1.0))

    span, peak, rec = longest_drawdown(eq, d)
    out.update(var95=float(var95), var99=float(var99), es975=float(r[r <= cut].mean()),
               skew=skew, excess_kurtosis=kurt - 3.0, worst_day=float(r.min()),
               best_day=float(r.max()), worst_week=worst(5), worst_month=worst(21),
               worst_year=worst(252), ulcer=ulcer_index(eq),
               underwater=float(np.mean(drawdowns(eq) < -1e-12)),
               longest_dd_days=span, longest_dd_peak=peak, longest_dd_recovery=rec,
               up_days=float(np.mean(r > 0)))
    mret = monthly_returns(eq, d)
    vals = [v for row in mret.values() for v in row["months"] if v is not None]
    out["up_months"] = float(np.mean(np.array(vals) > 0)) if vals else None
    if bench_equity is not None:
        b = np.asarray(bench_equity, dtype=np.float64)[ok]
        rb = returns(b)
        n = min(len(rb), len(r))
        if n > 20 and np.std(rb[:n]) > 0:
            c = np.cov(r[:n], rb[:n])
            out["beta"] = float(c[0, 1] / c[1, 1])
            out["correlation"] = float(np.corrcoef(r[:n], rb[:n])[0, 1])
            down = rb[:n] < 0
            if down.any():
                # how much of the benchmark's bad days the strategy took
                out["downside_capture"] = float(r[:n][down].mean() / rb[:n][down].mean())
    return out


def monthly_returns(equity, dates):
    """{year: {"months": [12 returns or None], "year": return}}: each month
    from the last close of the month before (or the first value)."""
    eq = np.asarray(equity, dtype=np.float64)
    d = np.asarray(dates, dtype="datetime64[D]")
    ok = np.isfinite(eq)
    eq, d = eq[ok], d[ok]
    out = {}
    if len(eq) < 2:
        return out
    months = d.astype("datetime64[M]")
    last_idx = np.nonzero(np.r_[months[1:] != months[:-1], True])[0]
    prev = eq[0]
    for i in last_idx:
        m = months[i]
        y = int(m.astype("datetime64[Y]").astype(int) + 1970)
        k = int(m.astype(int) % 12)
        row = out.setdefault(y, {"months": [None] * 12, "start": prev})
        row["months"][k] = float(eq[i] / prev - 1.0)
        row["end"] = float(eq[i])
        prev = eq[i]
    for y, row in out.items():
        row["year"] = row["end"] / row.pop("start") - 1.0
        row.pop("end")
    return out


def rolling_sharpe(equity, window=ind.TRADING_DAYS):
    """Annualised Sharpe of the trailing `window` daily returns (no
    risk-free rate), NaN until the window is full. Length = len(equity)."""
    eq = np.asarray(equity, dtype=np.float64)
    out = np.full(len(eq), np.nan)
    r = np.r_[np.nan, eq[1:] / eq[:-1] - 1.0]
    if len(eq) <= window:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    win = sliding_window_view(r[1:], window)
    mu, sd = win.mean(axis=1), win.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[window:] = np.where(sd > 0, mu / sd * np.sqrt(ind.TRADING_DAYS), np.nan)
    return out


def annual(sr_daily):
    return sr_daily * math.sqrt(ind.TRADING_DAYS)


def daily(sr_annual):
    return sr_annual / math.sqrt(ind.TRADING_DAYS)
