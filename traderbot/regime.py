"""Market regime: where the market stands on measures with research behind
them, and what followed each state in the past.

Every indicator turns daily closes into a state (an int, -1 = no data).
The states describe the environment; on their own they are not trading
signals. The research, and the history table here, say regimes forecast
the coming volatility much better than the coming return - which is why
the bot sizes positions by volatility instead of trying to time the market.
"""

import math
from statistics import NormalDist

import numpy as np

from . import indicators as ind

SECTORS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB"]
# NY Fed probit on the 10-year minus 3-month Treasury spread (Estrella and
# Mishkin): P(recession within 12 months) = N(-0.5333 - 0.6330 * spread)
CURVE_ALPHA, CURVE_BETA = -0.5333, -0.6330
_N = NormalDist()


def recession_probability(spread_pct):
    """12-month recession probability for a 10y-3m spread in percentage points."""
    if spread_pct is None or not np.isfinite(spread_pct):
        return None
    return float(_N.cdf(CURVE_ALPHA + CURVE_BETA * float(spread_pct)))


def _states(values, edges):
    """State index by thresholds: edges ascending, value < edges[0] -> 0 ..."""
    v = np.asarray(values, dtype=np.float64)
    out = np.searchsorted(np.asarray(edges, dtype=np.float64), v, side="right").astype(int)
    out[~np.isfinite(v)] = -1
    return out


class Indicator(object):
    key = ""
    name = ""
    symbols = ()
    labels = ()
    risk_on = ()           # state indices that count as risk-on in the summary
    unit = "pct"           # how to show the value: pct, num, ratio, pp
    about = ""
    source = ""

    def compute(self, panel):
        """(values, states) over the panel's dates."""
        raise NotImplementedError


class Trend(Indicator):
    key = "trend"
    name = "Trend (SPY / 200 günlük ortalama)"
    symbols = ("SPY",)
    labels = ("Ortalamanın altında", "Ortalamanın üstünde")
    risk_on = (1,)
    about = ("Fiyat 200 günlük ortalamasının üstündeyse uzun vadeli trend yukarı. Botun "
             "stratejisi de bu kuralı kullanır.")
    source = "Faber (2007); Moskowitz, Ooi ve Pedersen (2012)"

    def compute(self, panel):
        c = panel.close("SPY")
        v = c / ind.sma(c, 200) - 1.0
        return v, _states(v, [0.0])


class Momentum(Indicator):
    key = "momentum"
    name = "12 aylık momentum (SPY − hazine bonosu)"
    symbols = ("SPY", "BIL")
    labels = ("Negatif", "Pozitif")
    risk_on = (1,)
    about = ("Hisselerin son 12 aydaki getirisi hazine bonosunu geçiyorsa zaman serisi momentumu "
             "pozitif. Çift momentumun mutlak momentum ayağı.")
    source = "Moskowitz, Ooi ve Pedersen (2012); Antonacci (2014)"

    def compute(self, panel):
        spy = ind.momentum(panel.close("SPY"), 252)
        bil = ind.momentum(panel.close("BIL"), 252)
        v = spy - np.where(np.isfinite(bil), bil, 0.0)
        return v, _states(v, [0.0])


class RealizedVol(Indicator):
    key = "volatility"
    name = "Gerçekleşen oynaklık (SPY, 20 gün, yıllık)"
    symbols = ("SPY",)
    labels = ("Düşük (<%12)", "Normal (%12-20)", "Yüksek (>%20)")
    risk_on = (0, 1)
    about = ("Son 20 günün oynaklığı. Oynaklık kümelenir: sakin günleri sakin, fırtınalıyı "
             "fırtınalı günler izler. Bot pozisyon büyüklüğünü buna göre ayarlar.")
    source = "Moreira ve Muir (2017); Harvey ve diğ. (2018)"

    def compute(self, panel):
        v = ind.realized_vol(panel.close("SPY"), 20)
        return v, _states(v, [0.12, 0.20])


class Vix(Indicator):
    key = "vix"
    name = "VIX (beklenen oynaklık)"
    symbols = ("^VIX",)
    labels = ("Sakin (<15)", "Normal (15-25)", "Gergin (>25)")
    risk_on = (0, 1)
    unit = "num"
    about = "Opsiyon fiyatlarından çıkan, S&P 500'ün önümüzdeki 30 gündeki beklenen oynaklığı."
    source = "Cboe VIX endeksi"

    def compute(self, panel):
        v = panel.close("^VIX")
        return v, _states(v, [15.0, 25.0])


class VixTerm(Indicator):
    key = "vix_term"
    name = "VIX vade yapısı (VIX / VIX3M)"
    symbols = ("^VIX", "^VIX3M")
    labels = ("Normal eğim (<1)", "Ters eğim (≥1)")
    risk_on = (0,)
    unit = "ratio"
    about = ("Kısa vadeli korku 3 aylıktan yüksekse (oran ≥ 1) piyasa yakın vadeli stres "
             "fiyatlıyor. Hakemli bir getiri tahmini çalışması yok; durum tanımı olarak kullanın.")
    source = "Cboe; uygulayıcı göstergesi"

    def compute(self, panel):
        v = panel.close("^VIX") / panel.close("^VIX3M")
        return v, _states(v, [1.0])


class YieldCurve(Indicator):
    key = "curve"
    name = "Getiri eğrisi (10 yıl − 3 ay)"
    symbols = ("^TNX", "^IRX")
    labels = ("Ters (≤0)", "Normal (>0)")
    risk_on = (1,)
    unit = "pp"
    about = ("Uzun faiz kısa faizin altına inerse (ters eğri) ABD'de sonraki 6-24 ayda resesyon "
             "riski artar; 1970'ten beri her resesyondan önce görüldü, ama her terslenmeyi "
             "resesyon izlemedi ve zamanlaması belirsiz.")
    source = "Estrella ve Mishkin (1996, 1998); New York Fed"

    def compute(self, panel):
        v = panel.close("^TNX") - panel.close("^IRX")
        return v, _states(v, [1e-12])


class Credit(Indicator):
    key = "credit"
    name = "Kredi iştahı (HYG / IEF, 200 günlük ortalamaya göre)"
    symbols = ("HYG", "IEF")
    labels = ("Kaçış (altında)", "İştah var (üstünde)")
    risk_on = (1,)
    about = ("Yüksek getirili şirket tahvilleri devlet tahvilinden kötü gidiyorsa kredi "
             "piyasası riskten kaçıyor. Kredi primleri ekonomik yavaşlamaları önceden haber "
             "vermiştir.")
    source = "Gilchrist ve Zakrajšek (2012)"

    def compute(self, panel):
        ratio = panel.close("HYG") / panel.close("IEF")
        v = ratio / ind.sma(ratio, 200) - 1.0
        return v, _states(v, [0.0])


class Breadth(Indicator):
    key = "breadth"
    name = "Piyasa genişliği (200 gün ortalama üstündeki sektör payı)"
    symbols = tuple(SECTORS)
    labels = ("Dar (<%30)", "Karışık (%30-70)", "Geniş (≥%70)")
    risk_on = (2,)
    about = ("Dokuz sektör ETF'inden kaçı kendi 200 günlük ortalamasının üstünde. Yükselişe "
             "çok sektör katılıyorsa trend daha sağlam sayılır. Kanıtı zayıf, pratik bir gösterge.")
    source = "Uygulayıcı göstergesi (Zweig)"

    def compute(self, panel):
        above, ok = [], []
        for s in SECTORS:
            c = panel.close(s)
            ma = ind.sma(c, 200)
            ok.append(np.isfinite(ma) & np.isfinite(c))
            above.append(c > ma)
        ok = np.column_stack(ok)
        n = ok.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            v = np.where(n >= 5, (np.column_stack(above) & ok).sum(axis=1) / n, np.nan)
        return v, _states(v, [0.3, 0.7 - 1e-12])


INDICATORS = [Trend(), Momentum(), RealizedVol(), Vix(), VixTerm(), YieldCurve(), Credit(),
              Breadth()]
SYMBOLS = list(dict.fromkeys(s for i in INDICATORS for s in i.symbols))


def evaluate(panel):
    """{key: {"values", "states"} or None when a symbol is missing}."""
    out = {}
    for it in INDICATORS:
        if not all(s in panel.col for s in it.symbols):
            out[it.key] = None
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            values, states = it.compute(panel)
        out[it.key] = {"values": values, "states": states}
    return out


def snapshot(panel, results=None):
    """Today's reading: each indicator's latest value and state, plus the
    share of available indicators in a risk-on state."""
    results = results if results is not None else evaluate(panel)
    rows, on, n = [], 0, 0
    for it in INDICATORS:
        res = results.get(it.key)
        row = {"key": it.key, "name": it.name, "about": it.about, "source": it.source,
               "unit": it.unit, "value": None, "state": -1, "label": "veri yok",
               "risk_on": None, "date": None}
        if res is not None:
            ok = np.nonzero(res["states"] >= 0)[0]
            if len(ok):
                t = ok[-1]
                st = int(res["states"][t])
                row.update(value=float(res["values"][t]), state=st, label=it.labels[st],
                           risk_on=st in it.risk_on, date=str(panel.dates[t]))
                n += 1
                on += int(st in it.risk_on)
        if it.key == "curve" and row["value"] is not None:
            row["recession_probability"] = recession_probability(row["value"])
        rows.append(row)
    score = on / n if n else None
    if score is None:
        verdict = "Veri yok"
    elif score >= 2 / 3:
        verdict = "Risk iştahı yüksek"
    elif score > 1 / 3:
        verdict = "Karışık"
    else:
        verdict = "Temkinli"
    return {"rows": rows, "risk_on": on, "available": n, "score": score, "verdict": verdict}


def forward_returns(close, horizon):
    """close[t + h] / close[t] - 1, NaN where t + h is past the data."""
    c = np.asarray(close, dtype=np.float64)
    out = np.full(len(c), np.nan)
    if len(c) > horizon:
        out[:-horizon] = c[horizon:] / c[:-horizon] - 1.0
    return out


def forward_vol(close, horizon):
    """Annualised volatility of the daily returns in (t, t + h]."""
    c = np.asarray(close, dtype=np.float64)
    out = np.full(len(c), np.nan)
    if len(c) <= horizon + 1:
        return out
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.diff(np.log(c))
    from numpy.lib.stride_tricks import sliding_window_view
    win = sliding_window_view(r, horizon)          # win[k] = r[k .. k+h-1] = returns (k, k+h]
    out[:len(win)] = win.std(axis=1, ddof=1) * math.sqrt(ind.TRADING_DAYS)
    return out


def conditional_stats(panel, results=None, horizon=21, start=None, end=None, symbol="SPY"):
    """What `symbol` did over the next `horizon` days in each state of each
    indicator: share of days, mean and median return, share of rises, the
    5th percentile and the volatility that followed. Overlapping windows, so
    the day counts overstate the number of independent observations."""
    results = results if results is not None else evaluate(panel)
    c = panel.close(symbol)
    fwd, fvol = forward_returns(c, horizon), forward_vol(c, horizon)
    sel = np.isfinite(fwd) & np.isfinite(fvol)
    if start is not None:
        sel &= panel.dates >= np.datetime64(start, "D")
    if end is not None:
        sel &= panel.dates <= np.datetime64(end, "D")

    def stats(mask):
        x, v = fwd[mask], fvol[mask]
        if len(x) < 20:
            return None
        return {"days": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
                "up": float(np.mean(x > 0)), "p5": float(np.percentile(x, 5)),
                "vol": float(np.mean(v))}

    out = {"horizon": horizon, "all": stats(sel), "indicators": []}
    for it in INDICATORS:
        res = results.get(it.key)
        if res is None:
            continue
        have = sel & (res["states"] >= 0)
        total = int(have.sum())
        if total < 20:
            continue
        first = str(panel.dates[np.nonzero(have)[0][0]])
        rows = []
        for k, label in enumerate(it.labels):
            s = stats(have & (res["states"] == k))
            if s:
                s["share"] = s["days"] / total
            rows.append({"state": k, "label": label, "risk_on": k in it.risk_on, "stats": s})
        out["indicators"].append({"key": it.key, "name": it.name, "since": first, "rows": rows})
    return out
