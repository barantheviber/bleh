"""Price and indicator alerts, checked while the app runs.

An alert fires when its condition turns true - a crossing - not on every
check while it stays true. One-shot alerts switch themselves off after
firing. Alerts are plain dicts so they live in the settings file.
"""

import datetime as dt
import uuid

import numpy as np

from . import indicators as ind

KINDS = {
    "price_above": "Fiyat şunun üstüne çıkarsa",
    "price_below": "Fiyat şunun altına inerse",
    "change_up": "Gün içinde en az % yükselirse",
    "change_down": "Gün içinde en az % düşerse",
    "sma_up": "N günlük ortalamanın üstüne çıkarsa",
    "sma_down": "N günlük ortalamanın altına inerse",
    "rsi_above": "RSI(14) şunun üstüne çıkarsa",
    "rsi_below": "RSI(14) şunun altına inerse",
    "high_52w": "52 haftalık zirveyi aşarsa",
    "low_52w": "52 haftalık dibi kırarsa",
}
NO_VALUE = {"high_52w", "low_52w"}


class AlertError(ValueError):
    pass


def new_alert(symbol, kind, value=None, once=True, note="", now=None):
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise AlertError("Sembol gerekli")
    if kind not in KINDS:
        raise AlertError("Bilinmeyen alarm türü: %s" % kind)
    if kind in NO_VALUE:
        value = None
    else:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise AlertError("Bu alarm türü bir sayı ister")
        if value <= 0:
            raise AlertError("Değer sıfırdan büyük olmalı")
        if kind in ("sma_up", "sma_down"):
            if not 2 <= value <= 400:
                raise AlertError("Ortalama gün sayısı 2 ile 400 arasında olmalı")
            value = float(int(value))
        if kind in ("rsi_above", "rsi_below") and not 1 <= value <= 99:
            raise AlertError("RSI eşiği 1 ile 99 arasında olmalı")
    now = now or dt.datetime.now()
    return {"id": uuid.uuid4().hex[:10], "symbol": symbol, "kind": kind, "value": value,
            "once": bool(once), "enabled": True, "note": note, "last_state": None,
            "triggered_at": None, "created": now.replace(microsecond=0).isoformat()}


def describe(alert):
    v = alert.get("value")
    k = alert["kind"]
    if k in ("price_above", "price_below"):
        what = "fiyat %s %.2f" % ("≥" if k == "price_above" else "≤", v)
    elif k in ("change_up", "change_down"):
        what = "günlük değişim %s %%%.1f" % ("≥" if k == "change_up" else "≤ -", v)
    elif k in ("sma_up", "sma_down"):
        what = "%d günlük ortalamanın %s" % (v, "üstüne çıkış" if k == "sma_up" else "altına iniş")
    elif k in ("rsi_above", "rsi_below"):
        what = "RSI(14) %s %.0f" % (">" if k == "rsi_above" else "<", v)
    else:
        what = KINDS[k].lower()
    return "%s: %s" % (alert["symbol"], what)


def condition(alert, bars, price=None, prev_close=None):
    """(state, detail): whether the alert's condition holds now. state is
    None when the data cannot decide it. Daily bars, oldest first; Yahoo's
    newest bar is today's, still moving during the session."""
    c = np.asarray(bars.c, dtype=np.float64)
    if price is None and len(c):
        price = float(c[-1])
    if prev_close is None and len(c) >= 2:
        prev_close = float(c[-2])
    k, v = alert["kind"], alert.get("value")
    if price is None or not np.isfinite(price):
        return None, "fiyat yok"
    if k == "price_above":
        return bool(price >= v), "fiyat %.2f" % price
    if k == "price_below":
        return bool(price <= v), "fiyat %.2f" % price
    if k in ("change_up", "change_down"):
        if not prev_close:
            return None, "önceki kapanış yok"
        ch = 100.0 * (price / prev_close - 1.0)
        return bool(ch >= v if k == "change_up" else ch <= -v), "günlük değişim %+.2f%%" % ch
    if k in ("sma_up", "sma_down"):
        ma = ind.sma(c, int(v))[-1] if len(c) >= v else np.nan
        if not np.isfinite(ma):
            return None, "ortalama için veri az"
        return bool(price > ma if k == "sma_up" else price < ma), "fiyat %.2f, ortalama %.2f" % (
            price, ma)
    if k in ("rsi_above", "rsi_below"):
        r = ind.rsi(c, 14)[-1] if len(c) > 15 else np.nan
        if not np.isfinite(r):
            return None, "RSI için veri az"
        return bool(r > v if k == "rsi_above" else r < v), "RSI(14) %.1f" % r
    if k in ("high_52w", "low_52w"):
        if len(c) < 60:
            return None, "52 hafta için veri az"
        if k == "high_52w":
            top = float(np.nanmax(np.asarray(bars.h, dtype=np.float64)[-253:-1]))
            return bool(price > top), "fiyat %.2f, önceki zirve %.2f" % (price, top)
        low = float(np.nanmin(np.asarray(bars.l, dtype=np.float64)[-253:-1]))
        return bool(price < low), "fiyat %.2f, önceki dip %.2f" % (price, low)
    return None, "bilinmeyen tür"


def update(alert, state, now=None):
    """Record the newest state; True when the alert fires (false -> true)."""
    if state is None:
        return False
    state = bool(state)            # numpy booleans are not `True`
    fired = state and alert.get("last_state") is False
    alert["last_state"] = state
    if fired:
        alert["triggered_at"] = (now or dt.datetime.now()).replace(microsecond=0).isoformat()
        if alert.get("once"):
            alert["enabled"] = False
    return fired
