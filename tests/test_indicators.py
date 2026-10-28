import numpy as np
import pytest

from traderbot import indicators as ind

nan = np.nan


def close_to(a, b, tol=1e-9):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) < tol))


def test_sma():
    assert close_to(ind.sma([1, 2, 3, 4, 5], 3), [nan, nan, 2, 3, 4])
    assert close_to(ind.sma([1, 2], 3), [nan, nan])


def test_ema_seeded_with_sma():
    # alpha = 0.5, seed = mean(1, 2, 3) = 2, then 2 + .5*(4-2) = 3, 3 + .5*(5-3) = 4
    assert close_to(ind.ema([1, 2, 3, 4, 5], 3), [nan, nan, 2, 3, 4])


def test_rsi2_hand_computed():
    # closes 10 11 10 12 11 -> gains 1 0 2 0, losses 0 1 0 1 (Wilder smoothing, n=2)
    out = ind.rsi([10, 11, 10, 12, 11], 2)
    assert close_to(out, [nan, nan, 50.0, 100 - 100 / 6, 50.0], 1e-9)


def test_rsi_extremes_and_bounds():
    up = np.arange(1, 40, dtype=float)
    assert np.all(ind.rsi(up, 14)[14:] == 100)
    assert np.all(ind.rsi(up[::-1], 14)[14:] == 0)
    assert np.all(ind.rsi(np.full(30, 5.0), 14)[14:] == 50)
    x = 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 500))
    r = ind.rsi(x, 14)
    assert np.nanmin(r) >= 0 and np.nanmax(r) <= 100


def test_macd_parts():
    x = 100 + np.cumsum(np.random.default_rng(2).normal(0, 1, 200))
    line, sig, hist = ind.macd(x)
    assert close_to(line, ind.ema(x, 12) - ind.ema(x, 26))
    assert np.isnan(sig[:33]).all() and np.isfinite(sig[33:]).all()
    assert close_to(hist, line - sig)


def test_bollinger_width_is_2k_std():
    x = np.array([1, 2, 3, 4, 5, 6], float)
    mid, up, lo = ind.bollinger(x, 3, 2.0)
    sd = np.std([1, 2, 3])
    assert np.isclose(up[2] - lo[2], 4 * sd) and np.isclose(mid[2], 2)


def test_atr_constant_range():
    h = np.full(20, 11.0)
    l = np.full(20, 9.0)
    c = np.full(20, 10.0)
    assert np.allclose(ind.atr(h, l, c, 5)[4:], 2.0)


def test_true_range_uses_gap():
    tr = ind.true_range([10, 15], [9, 14], [9.5, 14.5])
    assert tr[0] == 1 and tr[1] == 15 - 9.5


def test_rolling_extremes_and_momentum():
    x = [3, 1, 4, 1, 5, 9, 2]
    assert close_to(ind.rolling_max(x, 3), [nan, nan, 4, 4, 5, 9, 9])
    assert close_to(ind.rolling_min(x, 3), [nan, nan, 1, 1, 1, 1, 2])
    assert close_to(ind.momentum([10, 11, 12.1], 1), [nan, 0.1, 0.1], 1e-12)


def test_realized_vol_of_steady_growth_is_zero():
    x = 100 * 1.001 ** np.arange(60)
    v = ind.realized_vol(x, 20)
    assert np.all(np.isnan(v[:20])) and np.allclose(v[20:], 0, atol=1e-12)


def test_leading_nan_does_not_poison_later_values():
    """Panels hold NaN before a fund's first day; indicators must start
    cleanly once data exists (a cumsum over NaN used to break sma)."""
    x = 100 + np.cumsum(np.random.default_rng(4).normal(0, 1, 300))
    lead = np.concatenate([np.full(50, np.nan), x])
    assert close_to(ind.sma(lead, 20)[50:], ind.sma(x, 20))
    assert close_to(ind.rsi(lead, 14)[50:], ind.rsi(x, 14))
    assert close_to(ind.ema(lead, 20)[50:], ind.ema(x, 20))
    assert close_to(ind.atr(lead + 1, lead - 1, lead, 14)[50:], ind.atr(x + 1, x - 1, x, 14))
    assert np.isnan(ind.rsi(lead, 14)[:64]).all()


def test_sma_window_with_a_gap_is_nan_only_there():
    x = np.arange(10, dtype=float)
    x[4] = np.nan
    out = ind.sma(x, 3)
    assert np.isnan(out[4:7]).all() and out[7] == 6 and out[3] == 2


@pytest.mark.parametrize("fn", [
    lambda x: ind.sma(x, 20), lambda x: ind.ema(x, 20), lambda x: ind.rsi(x, 14),
    lambda x: ind.rsi(x, 2), lambda x: ind.macd(x)[1], lambda x: ind.bollinger(x)[1],
    lambda x: ind.atr(x + 1, x - 1, x, 14), lambda x: ind.momentum(x, 63),
    lambda x: ind.realized_vol(x, 20), lambda x: ind.rolling_max(x, 50),
])
def test_no_look_ahead(fn):
    """A value at t must not change when data after t is added."""
    x = 100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 400))
    full = fn(x)
    for k in (60, 150, 399):
        assert close_to(fn(x[:k]), full[:k], 1e-9)
