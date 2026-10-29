"""Position sizing: how big a position should be, from the risk accepted.

- fixed_fractional: lose at most `risk_pct` of the account if the stop is
  hit (the "1R" of trading practice). Long positions only.
- kelly: the growth-optimal bet fraction for a win rate and a payoff ratio
  (Kelly 1956). Estimates of both are noisy, so the research favours a
  fraction of it (MacLean, Thorp and Ziemba 2010).
- vol_target_weight: the bot's own rule, hold less of an asset when it is
  more volatile (Moreira and Muir 2017).
"""

import math


class SizingError(ValueError):
    pass


def atr_stop(entry, atr, multiple=2.0):
    """Stop `multiple` average true ranges below the entry."""
    if not atr or atr <= 0:
        raise SizingError("ATR hesaplanamadı")
    return entry - multiple * atr


def fixed_fractional(equity, risk_pct, entry, stop, max_position_pct=100.0, fractional=True):
    """Shares such that falling from `entry` to `stop` loses `risk_pct`% of
    `equity`, capped so the position is at most `max_position_pct`% of it."""
    if equity <= 0:
        raise SizingError("Hesap değeri pozitif olmalı")
    if entry <= 0:
        raise SizingError("Giriş fiyatı pozitif olmalı")
    if not 0 < risk_pct <= 100:
        raise SizingError("Risk yüzdesi 0 ile 100 arasında olmalı")
    per_share = entry - stop
    if stop <= 0 or per_share <= 0:
        raise SizingError("Stop, giriş fiyatının altında ve sıfırdan büyük olmalı (yalnız uzun "
                          "pozisyon)")
    risk_usd = equity * risk_pct / 100.0
    shares = risk_usd / per_share
    cap = equity * max_position_pct / 100.0 / entry
    capped = shares > cap
    shares = min(shares, cap)
    if not fractional:
        shares = math.floor(shares)
    value = shares * entry
    return {"shares": shares, "value": value, "weight": value / equity,
            "risk_usd": shares * per_share, "risk_pct": 100.0 * shares * per_share / equity,
            "per_share": per_share, "stop": stop, "stop_pct": per_share / entry,
            "capped": capped, "targets": {k: entry + k * per_share for k in (1, 2, 3)}}


def losing_streak(risk_pct, n):
    """Account left after n losses in a row at risk_pct% each (as a drop)."""
    return (1.0 - risk_pct / 100.0) ** n - 1.0


def kelly(win_rate, payoff):
    """Kelly fraction p - (1 - p) / b for a trade that wins b for every 1 it
    loses. Negative means the system loses money on average: do not trade it."""
    if not 0 <= win_rate <= 1:
        raise SizingError("Kazanma oranı 0 ile 1 arasında olmalı")
    if payoff <= 0:
        raise SizingError("Kazanç/kayıp oranı pozitif olmalı")
    return win_rate - (1.0 - win_rate) / payoff


def expectancy(win_rate, avg_win, avg_loss):
    """Average result per trade, in the units of avg_win/avg_loss (losses
    given as positive numbers)."""
    return win_rate * avg_win - (1.0 - win_rate) * avg_loss


def vol_target_weight(asset_vol, target_vol, cap=1.0):
    """Share of the account to hold so the position's volatility is about
    `target_vol` (both annualised, e.g. 0.15)."""
    if not asset_vol or asset_vol <= 0:
        raise SizingError("Varlığın oynaklığı hesaplanamadı")
    return min(cap, target_vol / asset_vol)
