"""Daily portfolio backtester shared by the research study, the Backtest tab
and the bot's dry runs.

Model:
- A strategy gives target weights per day, decided with data up to that
  day's close (row t of the weight matrix).
- Orders go in at the NEXT day's open (t+1), fractional shares, no leverage:
  weights that sum above 1 are scaled down, the rest stays in cash at 0%.
- A trade happens when the target changes, or when a holding has drifted more
  than `band` (default 5 points, trader-rebalance's default) from target.
- Every traded dollar pays `cost_bps` (spread + slippage + fees).
"""

import datetime as _dt

import numpy as np

from . import indicators as ind


class Panel(object):
    """Several symbols' daily bars on one calendar. Arrays are (T, N); a
    symbol is NaN before its first bar."""

    def __init__(self, dates, symbols, o, h, l, c, v, next_session=None):
        self.dates = dates
        # the trading day after the last row, when known (live use): lets
        # monthly strategies tell whether the newest bar closed a month
        self.next_session = next_session
        self.symbols = list(symbols)
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        self.col = {s: i for i, s in enumerate(self.symbols)}

    def __len__(self):
        return len(self.dates)

    def close(self, sym):
        return self.c[:, self.col[sym]]

    def first_valid(self, sym):
        ok = np.nonzero(np.isfinite(self.close(sym)))[0]
        return int(ok[0]) if len(ok) else None

    def index_of(self, date, side="left"):
        return int(np.searchsorted(self.dates, np.datetime64(date, "D"), side=side))


def build_panel(bars_by_symbol, calendar_symbol=None, adjusted=True, ffill_limit=5):
    """Panel on `calendar_symbol`'s trading days (default: every date any
    symbol traded). Short gaps after a symbol's first bar are carried forward
    from the last close, up to `ffill_limit` days; nothing before it is filled."""
    if not bars_by_symbol:
        raise ValueError("no symbols")
    series = {}
    for sym, b in bars_by_symbol.items():
        b = b.adjusted() if adjusted else b
        d = b.dates()
        _, last = np.unique(d[::-1], return_index=True)
        keep = np.sort(len(d) - 1 - last)
        series[sym] = (d[keep], b.take(keep))
    if calendar_symbol:
        dates = series[calendar_symbol][0]
    else:
        dates = np.unique(np.concatenate([d for d, _ in series.values()]))
    syms = list(bars_by_symbol)
    T, N = len(dates), len(syms)
    arrs = {k: np.full((T, N), np.nan) for k in "ohlcv"}
    for j, sym in enumerate(syms):
        d, b = series[sym]
        pos = np.searchsorted(dates, d)
        ok = (pos < T) & (dates[np.minimum(pos, T - 1)] == d)
        for k, src in (("o", b.o), ("h", b.h), ("l", b.l), ("c", b.c), ("v", b.v)):
            arrs[k][pos[ok], j] = src[ok]
        _ffill_column(arrs, j, ffill_limit)
    return Panel(dates, syms, arrs["o"], arrs["h"], arrs["l"], arrs["c"], arrs["v"])


def _ffill_column(arrs, j, limit):
    c = arrs["c"][:, j]
    valid = np.nonzero(np.isfinite(c))[0]
    if not len(valid):
        return
    gap = 0
    for t in range(valid[0] + 1, len(c)):
        if np.isfinite(c[t]):
            gap = 0
            continue
        gap += 1
        if gap > limit:
            continue
        prev = arrs["c"][t - 1, j]
        if not np.isfinite(prev):
            continue
        for k in "ohlc":
            arrs[k][t, j] = prev
        arrs["v"][t, j] = 0.0


class Trade(object):
    __slots__ = ("date", "symbol", "side", "qty", "price", "value", "cost")

    def __init__(self, date, symbol, side, qty, price, value, cost):
        self.date, self.symbol, self.side = date, symbol, side
        self.qty, self.price, self.value, self.cost = qty, price, value, cost

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Result(object):
    def __init__(self, dates, equity, weights, symbols, trades, start, end, capital):
        self.dates = dates
        self.equity = equity
        self.weights = weights      # (T, N) weights held at each close
        self.symbols = symbols
        self.trades = trades
        self.start, self.end = start, end
        self.capital = capital

    def window(self):
        s, e = self.start, self.end
        return self.dates[s:e + 1], self.equity[s:e + 1]

    def metrics(self, rf_daily=None):
        d, eq = self.window()
        m = metrics(eq, d, None if rf_daily is None else rf_daily[self.start:self.end + 1])
        m.update(trade_stats(self.trades, self.equity[self.start:self.end + 1], m["years"]))
        held = self.weights[self.start:self.end + 1]
        m["exposure"] = float(np.mean(np.nansum(held, axis=1) > 0.01)) if len(held) else 0.0
        return m


def backtest_strategy(strategy, panel, start=None, end=None, **kw):
    """Weights from `strategy` on `panel`, simulated with run_backtest."""
    kw.setdefault("trade_on_change", strategy.trade_on_change)
    return run_backtest(panel, strategy.weights(panel), strategy.symbols(), start, end, **kw)


def run_backtest(panel, weights, symbols, start=None, end=None, capital=10000.0,
                 cost_bps=5.0, band=0.05, trade_on_change=True):
    """Simulate `weights` (T, len(symbols)), decided at each close, filled at
    the next open. `start`/`end` are dates or indices limiting the equity
    window; signals before `start` are ignored (the account opens in cash).
    With trade_on_change=False only drift past `band` triggers a trade."""
    T = len(panel)
    W = np.asarray(weights, dtype=np.float64)
    if W.shape != (T, len(symbols)):
        raise ValueError("weights must be (%d, %d), got %s" % (T, len(symbols), W.shape))
    cols = [panel.col[s] for s in symbols]
    O, C = panel.o[:, cols], panel.c[:, cols]
    s = _as_index(panel, start, 0)
    e = _as_index(panel, end, T - 1, side="right")
    k = cost_bps / 1e4
    N = len(symbols)

    units = np.zeros(N)
    cash = float(capital)
    last_px = np.full(N, np.nan)
    equity = np.full(T, np.nan)
    held_w = np.zeros((T, N))
    trades = []
    pending, changed, prev_target = None, False, None

    for t in range(s, e + 1):
        # 1) fill the order decided at yesterday's close at today's open
        if pending is not None:
            px = O[t]
            tradable = np.isfinite(px) & (px > 0)
            mark = np.where(tradable, px, last_px)
            value = cash + float(np.nansum(units * mark))
            target = np.where(tradable, pending, 0.0)
            # a holding that cannot trade today keeps its units
            stuck = (~tradable) & (units != 0)
            cur_w = np.where(np.isfinite(mark), units * mark, 0.0) / value if value > 0 else 0 * units
            drift = np.max(np.abs(np.where(tradable, cur_w - target, 0.0))) if N else 0.0
            if value > 0 and ((changed and trade_on_change) or drift > band + 1e-12):
                free = value - float(np.nansum(np.where(stuck, units * mark, 0.0)))
                tot = target.sum()
                if tot > 1.0:
                    target = target / tot
                post = free
                for _ in range(3):  # costs come out of the money that is invested
                    want = np.where(tradable, target * post / np.where(tradable, px, 1.0), units)
                    notional = np.abs(want - units) * np.where(tradable, px, 0.0)
                    cost = k * float(notional.sum())
                    post = free - cost
                want = np.where(tradable, target * post / np.where(tradable, px, 1.0), units)
                delta = want - units
                for j in np.nonzero(np.abs(delta) * np.where(tradable, px, 0.0) > 1e-6)[0]:
                    v = float(delta[j] * px[j])
                    trades.append(Trade(_date_str(panel.dates[t]), symbols[j],
                                        "buy" if delta[j] > 0 else "sell", float(abs(delta[j])),
                                        float(px[j]), abs(v), k * abs(v)))
                cash -= float(np.sum(np.where(tradable, delta * px, 0.0))) + cost
                units = np.where(tradable, want, units)
                units[np.abs(units) < 1e-12] = 0.0
            pending, changed = None, False
        # 2) mark to market at today's close
        px = C[t]
        ok = np.isfinite(px)
        last_px = np.where(ok, px, last_px)
        pos_val = np.where(np.isfinite(last_px), units * last_px, 0.0)
        equity[t] = cash + float(pos_val.sum())
        if equity[t] > 0:
            held_w[t] = pos_val / equity[t]
        # 3) today's close decides tomorrow's order
        w = W[t]
        if t < e and np.all(np.isfinite(w)):
            w = np.clip(w, 0.0, None)
            if prev_target is None or np.max(np.abs(w - prev_target)) > 1e-9:
                changed = True
            prev_target = w.copy()
            pending = w
    return Result(panel.dates, equity, held_w, list(symbols), trades, s, e, capital)


def _as_index(panel, x, default, side="left"):
    if x is None:
        return default
    if isinstance(x, (int, np.integer)):
        return int(x)
    i = panel.index_of(x, side=side)
    return i - 1 if side == "right" else i


def _date_str(d):
    return str(np.datetime64(d, "D"))


# ---------------------------------------------------------------- metrics

def metrics(equity, dates, rf_daily=None):
    """Performance of a daily equity curve. rf_daily is the cash return per
    day (e.g. from BIL) for the excess-return Sharpe; None means 0%."""
    eq = np.asarray(equity, dtype=np.float64)
    ok = np.isfinite(eq)
    eq, dates = eq[ok], np.asarray(dates)[ok]
    out = {"start": _date_str(dates[0]) if len(dates) else None,
           "end": _date_str(dates[-1]) if len(dates) else None}
    if len(eq) < 2:
        out.update(years=0.0, total_return=0.0, cagr=0.0, vol=0.0, sharpe=0.0,
                   sharpe_excess=0.0, sortino=0.0, max_dd=0.0, calmar=0.0, dd_peak=None,
                   dd_trough=None, best_year=None, worst_year=None)
        return out
    r = eq[1:] / eq[:-1] - 1.0
    days = (dates[-1] - dates[0]).astype("timedelta64[D]").astype(int)
    years = max(days / 365.25, 1e-9)
    total = eq[-1] / eq[0] - 1.0
    cagr = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0 if eq[-1] > 0 else -1.0
    sd = r.std(ddof=1)
    vol = sd * np.sqrt(ind.TRADING_DAYS)
    sharpe = r.mean() / sd * np.sqrt(ind.TRADING_DAYS) if sd > 0 else 0.0
    if rf_daily is not None:
        rf = np.asarray(rf_daily, dtype=np.float64)[ok][1:]
        rf = np.where(np.isfinite(rf), rf, 0.0)
        ex = r - rf
        sharpe_ex = ex.mean() / ex.std(ddof=1) * np.sqrt(ind.TRADING_DAYS) if ex.std(ddof=1) > 0 else 0.0
    else:
        sharpe_ex = sharpe
    down = r[r < 0]
    dsd = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)) if len(down) else 0.0
    sortino = r.mean() / dsd * np.sqrt(ind.TRADING_DAYS) if dsd > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    trough = int(np.argmin(dd))
    peak_i = int(np.argmax(eq[:trough + 1])) if trough > 0 else 0
    max_dd = float(dd[trough])
    years_s = dates.astype("datetime64[Y]")
    yearly = {}
    for y in np.unique(years_s):
        sel = np.nonzero(years_s == y)[0]
        base = eq[sel[0] - 1] if sel[0] > 0 else eq[sel[0]]
        yearly[str(y)] = float(eq[sel[-1]] / base - 1.0)
    out.update(years=float(years), total_return=float(total), cagr=float(cagr), vol=float(vol),
               sharpe=float(sharpe), sharpe_excess=float(sharpe_ex), sortino=float(sortino),
               max_dd=max_dd, calmar=float(cagr / abs(max_dd)) if max_dd < 0 else 0.0,
               dd_peak=_date_str(dates[peak_i]), dd_trough=_date_str(dates[trough]),
               yearly=yearly,
               best_year=max(yearly.items(), key=lambda kv: kv[1]) if yearly else None,
               worst_year=min(yearly.items(), key=lambda kv: kv[1]) if yearly else None)
    return out


def trades_from_orders(orders):
    """A broker's filled (or partly filled) orders as Trades, oldest first, so
    the live account gets the same round-trip statistics as a backtest."""
    out = []
    for o in sorted(orders, key=lambda o: o.filled_at or o.created_at or ""):
        qty = float(o.filled_qty or 0)
        px = float(o.filled_avg_price or 0)
        if qty <= 0 or px <= 0 or o.side not in ("buy", "sell"):
            continue
        out.append(Trade(str(o.filled_at or o.created_at or "")[:10], o.symbol, o.side, qty, px,
                         qty * px, 0.0))
    return out


def trade_stats(trades, equity, years):
    """Round trips per symbol on an average-cost basis: a trip opens when a
    position goes from flat to long and closes when it is flat again."""
    pos, cost, bought, realized = {}, {}, {}, {}
    trips, pnls = [], []
    traded = 0.0
    for tr in trades:
        traded += tr.value
        s = tr.symbol
        q = pos.get(s, 0.0)
        if tr.side == "buy":
            if q <= 1e-12:
                cost[s], bought[s], realized[s] = 0.0, 0.0, 0.0
            pos[s] = q + tr.qty
            cost[s] = cost.get(s, 0.0) + tr.value + tr.cost
            bought[s] = bought.get(s, 0.0) + tr.value + tr.cost
        else:
            if q <= 1e-12:
                continue
            avg = cost[s] / q
            sold = min(tr.qty, q)
            realized[s] = realized.get(s, 0.0) + sold * tr.price - tr.cost - sold * avg
            cost[s] -= sold * avg
            pos[s] = q - sold
            if pos[s] <= 1e-9 * max(1.0, q):
                pos[s] = 0.0
                trips.append(realized[s] / bought[s] if bought[s] > 0 else 0.0)
                pnls.append(realized[s])
    eq = np.asarray(equity, dtype=np.float64)
    avg_eq = float(np.nanmean(eq)) if len(eq) else 0.0
    wins = [x for x in trips if x > 0]
    losses = [-x for x in trips if x < 0]
    gain = sum(x for x in pnls if x > 0)
    lost = -sum(x for x in pnls if x < 0)
    return {"trades": len(trades), "round_trips": len(trips),
            "win_rate": len(wins) / len(trips) if trips else None,
            "avg_trip": float(np.mean(trips)) if trips else None,
            # per-trip returns of winners and losers (losses as positive numbers)
            "avg_win": float(np.mean(wins)) if wins else None,
            "avg_loss": float(np.mean(losses)) if losses else None,
            "payoff": float(np.mean(wins) / np.mean(losses)) if wins and losses else None,
            "profit_factor": gain / lost if lost > 0 else None,
            "realized": float(sum(pnls)),
            "turnover": (traded / 2.0) / avg_eq / years if avg_eq > 0 and years > 0 else 0.0}
