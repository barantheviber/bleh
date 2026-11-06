"""Rank symbols on measures with research behind them.

- 12-1 month momentum: the return from 12 months ago to 1 month ago; the
  latest month is skipped because it tends to reverse (Jegadeesh and
  Titman 1993).
- Distance from the 52-week high: stocks near their high kept outperforming
  those far from it (George and Hwang 2004).
- Trend: price against its 200-day average (Faber 2007).
- RSI(2) pullback in an uptrend: Connors' short-term entry. It worked well
  before 2010 and weakly since (the strategy study tests it).
The score ranks only the two momentum measures; it is a starting point for
a look at the chart, not a buy list.
"""

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import indicators as ind
from .data.yahoo import DataError

UNIVERSES = {
    "Sektör ETF'leri (SPDR)": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB",
                               "XLRE", "XLC"],
    "Varlık sınıfları": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "TIP", "LQD", "HYG",
                         "GLD", "SLV", "DBC", "VNQ", "BIL"],
    "Ülke ETF'leri": ["SPY", "EWJ", "EWG", "EWU", "EWQ", "EWI", "EWP", "EWL", "EWC", "EWA",
                      "EWZ", "EWW", "FXI", "INDA", "EWY", "EWT", "EZA", "TUR"],
    "ABD büyük şirketler": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "AVGO",
                            "TSLA", "JPM", "LLY", "V", "XOM", "UNH", "MA", "COST", "HD", "PG",
                            "JNJ", "WMT", "NFLX", "ORCL", "KO", "BAC"],
    "BIST büyükleri (örnek liste)": ["THYAO.IS", "ASELS.IS", "GARAN.IS", "AKBNK.IS", "BIMAS.IS",
                                     "KCHOL.IS", "SAHOL.IS", "TUPRS.IS", "EREGL.IS", "SISE.IS",
                                     "YKBNK.IS", "ISCTR.IS", "FROTO.IS", "TCELL.IS", "PGSUS.IS",
                                     "TOASO.IS", "ARCLK.IS", "ENKAI.IS", "TTKOM.IS", "SASA.IS"],
}
MONTH = 21
YEAR = 252


def _ret(c, a, b):
    """c[a] / c[b] - 1 for negative indices, None when out of range."""
    if len(c) < max(-a, -b):
        return None
    x, y = c[a], c[b]
    return float(x / y - 1.0) if np.isfinite(x) and np.isfinite(y) and y > 0 else None


def measure(bars):
    """Screen measures for one symbol's daily bars (oldest first)."""
    adj = bars.adjusted()
    c = np.asarray(adj.c, dtype=np.float64)
    h = np.asarray(adj.h, dtype=np.float64)
    v = np.asarray(bars.v, dtype=np.float64)
    out = {"symbol": bars.symbol, "price": float(bars.c[-1]), "date": bars.date_str(-1),
           "change": _ret(c, -1, -2), "mom_12_1": _ret(c, -(MONTH + 1), -(YEAR + 1)),
           "mom_6": _ret(c, -1, -(6 * MONTH + 1)), "from_high": None, "trend": None,
           "vol": None, "rsi2": None, "volume_ratio": None, "pullback": False}
    if len(c) >= YEAR:
        out["from_high"] = float(c[-1] / np.nanmax(h[-YEAR:]) - 1.0)
    if len(c) >= 200:
        ma = ind.sma(c, 200)[-1]
        out["trend"] = float(c[-1] / ma - 1.0) if np.isfinite(ma) else None
    if len(c) > 21:
        vol = ind.realized_vol(c, 20)[-1]
        out["vol"] = float(vol) if np.isfinite(vol) else None
        r2 = ind.rsi(c, 2)[-1]
        out["rsi2"] = float(r2) if np.isfinite(r2) else None
    if len(v) > 51:
        base = np.nanmean(v[-51:-1])
        out["volume_ratio"] = float(v[-1] / base) if base > 0 else None
    out["pullback"] = bool(out["trend"] is not None and out["trend"] > 0 and
                           out["rsi2"] is not None and out["rsi2"] < 10)
    return out


def _pct_rank(values):
    """Percentile rank 0..100 of each value (ties share the average rank)."""
    x = np.asarray(values, dtype=np.float64)
    order = x.argsort(kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x))
    for v in np.unique(x):
        same = x == v
        ranks[same] = ranks[same].mean()
    return 100.0 * ranks / max(1, len(x) - 1)


def score(rows):
    """Add 'score' (0-100): the average percentile rank of 12-1 momentum and
    of closeness to the 52-week high, among rows that have both."""
    have = [r for r in rows if r.get("mom_12_1") is not None and r.get("from_high") is not None]
    for r in rows:
        r["score"] = None
    if len(have) >= 2:
        a = _pct_rank([r["mom_12_1"] for r in have])
        b = _pct_rank([r["from_high"] for r in have])
        for r, x, y in zip(have, a, b):
            r["score"] = float((x + y) / 2.0)
    return rows


def screen(data, symbols, range_="2y", workers=6):
    """Fetch and measure `symbols` in parallel. Returns (rows sorted by score,
    {symbol: error})."""
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    failed = {}

    def one(sym):
        try:
            bars = data.bars(sym, "1d", range_)[0]
        except DataError as exc:
            return sym, None, str(exc)
        if bars is None or len(bars) < 30:
            return sym, None, "yeterli veri yok"
        return sym, measure(bars), None

    rows = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, row, err in pool.map(one, symbols):
            if row is None:
                failed[sym] = err
            else:
                row["symbol"] = sym
                rows.append(row)
    score(rows)
    rows.sort(key=lambda r: -1 if r["score"] is None else r["score"], reverse=True)
    return rows, failed
