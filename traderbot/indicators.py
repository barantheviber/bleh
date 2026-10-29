"""Technical indicators on numpy arrays, oldest first.

Every function returns an array the length of its input, with NaN where the
window is not yet full. A value at index t uses data up to and including t
only, so a signal computed at t can be acted on at t+1 without look-ahead.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

TRADING_DAYS = 252


def _arr(x):
    return np.asarray(x, dtype=np.float64)


def sma(x, n):
    """Simple moving average. A window holding any NaN (e.g. days before a
    fund existed) is NaN; later windows are not affected."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    n = int(n)
    if n <= 0 or len(x) < n:
        return out
    bad = ~np.isfinite(x)
    c = np.cumsum(np.insert(np.where(bad, 0.0, x), 0, 0.0))
    nbad = np.cumsum(np.insert(bad.astype(np.int64), 0, 0))
    mean = (c[n:] - c[:-n]) / n
    out[n - 1:] = np.where(nbad[n:] - nbad[:-n] == 0, mean, np.nan)
    return out


def ema(x, n):
    """Exponential moving average, alpha = 2/(n+1), seeded with the SMA of
    the first n values (the usual charting convention). NaNs at the start of
    x (an indicator's own warm-up) are skipped."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    n = int(n)
    valid = np.nonzero(np.isfinite(x))[0]
    if n <= 0 or len(valid) < n:
        return out
    s = valid[0]
    alpha = 2.0 / (n + 1)
    prev = np.mean(x[s:s + n])
    out[s + n - 1] = prev
    for i in range(s + n, len(x)):
        v = x[i]
        if np.isfinite(v):
            prev = prev + alpha * (v - prev)
        out[i] = prev
    return out


def rma(x, n):
    """Wilder's moving average (alpha = 1/n), seeded with an SMA."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    n = int(n)
    valid = np.nonzero(np.isfinite(x))[0]
    if n <= 0 or len(valid) < n:
        return out
    s = valid[0]
    prev = np.mean(x[s:s + n])
    out[s + n - 1] = prev
    for i in range(s + n, len(x)):
        v = x[i]
        if np.isfinite(v):
            prev = (prev * (n - 1) + v) / n
        out[i] = prev
    return out


def rsi(close, n=14):
    """Wilder's RSI. RSI(2) (Connors) is rsi(close, 2)."""
    c = _arr(close)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    # a NaN change (no price yet) stays NaN instead of counting as a flat day
    gain = np.concatenate([[np.nan], np.where(np.isfinite(d), np.where(d > 0, d, 0.0), np.nan)])
    loss = np.concatenate([[np.nan], np.where(np.isfinite(d), np.where(d < 0, -d, 0.0), np.nan)])
    ag, al = rma(gain, n), rma(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        out = 100.0 - 100.0 / (1.0 + rs)
    out = np.where((al == 0) & (ag > 0), 100.0, out)
    out = np.where((al == 0) & (ag == 0), 50.0, out)
    out[~np.isfinite(ag)] = np.nan
    return out


def macd(close, fast=12, slow=26, signal=9):
    """(macd line, signal line, histogram)."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(close, n=20, k=2.0):
    """(middle, upper, lower) with a population standard deviation."""
    c = _arr(close)
    mid = sma(c, n)
    sd = rolling_std(c, n)
    return mid, mid + k * sd, mid - k * sd


def rolling_std(x, n, ddof=0):
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n > ddof:
        out[n - 1:] = sliding_window_view(x, n).std(axis=1, ddof=ddof)
    return out


def rolling_max(x, n):
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n > 0:
        out[n - 1:] = sliding_window_view(x, n).max(axis=1)
    return out


def rolling_min(x, n):
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n > 0:
        out[n - 1:] = sliding_window_view(x, n).min(axis=1)
    return out


def true_range(high, low, close):
    h, l, c = _arr(high), _arr(low), _arr(close)
    prev = np.concatenate([[np.nan], c[:-1]])
    tr = np.fmax(h - l, np.fmax(np.abs(h - prev), np.abs(l - prev)))
    tr[0] = h[0] - l[0]
    return tr


def atr(high, low, close, n=14):
    return rma(true_range(high, low, close), n)


def momentum(close, n):
    """Return over the last n bars: close[t] / close[t-n] - 1."""
    c = _arr(close)
    out = np.full(len(c), np.nan)
    if len(c) > n > 0:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[n:] = c[n:] / c[:-n] - 1.0
    return out


def realized_vol(close, n=20, periods=TRADING_DAYS):
    """Annualised standard deviation of daily log returns over n bars."""
    c = _arr(close)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.concatenate([[np.nan], np.diff(np.log(c))])
    out = np.full(len(c), np.nan)
    if len(c) > n:
        out[n:] = sliding_window_view(r[1:], n).std(axis=1, ddof=1) * np.sqrt(periods)
    return out
