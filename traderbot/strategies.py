"""Trading strategies as target-weight matrices.

A strategy reads a Panel and returns weights (T, len(symbols())) where row t
uses data up to the close of day t only. NaN rows mean "not ready yet". The
backtester fills row t at the open of t+1; the bot does the same live, from
the last completed daily bar.

Every strategy here is long only, unleveraged, and parks the money it does
not invest in a T-bill ETF (BIL by default) or, before that ETF existed, cash.
"""

import numpy as np

from . import indicators as ind
from . import market_clock

SECTORS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB"]
ROTATION_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
# one ETF per asset class: US, developed and emerging stocks, Treasuries, gold,
# commodities, real estate
ASSET_CLASSES = ["SPY", "EFA", "EEM", "IEF", "GLD", "DBC", "VNQ"]
# Faber (2007): US stocks, foreign stocks, 10-year Treasuries, commodities, REITs
FABER_UNIVERSE = ["SPY", "EFA", "IEF", "DBC", "VNQ"]
MONTH = 21  # trading days


class Strategy(object):
    key = ""
    name = ""
    summary = ""
    params = {}
    # continuous-weight strategies trade only when a holding drifts past the
    # band, not on every tiny change of target
    trade_on_change = True

    def __init__(self, **kw):
        unknown = set(kw) - set(self.params)
        if unknown:
            raise ValueError("%s: unknown parameter(s) %s" % (self.key, ", ".join(sorted(unknown))))
        self.p = dict(self.params)
        self.p.update(kw)

    def symbols(self):
        raise NotImplementedError

    def inputs(self):
        """Symbols whose prices the strategy reads (default: the ones it holds)."""
        return self.symbols()

    def warmup(self):
        """Bars of history needed before the first signal."""
        return 0

    def weights(self, panel):
        raise NotImplementedError

    def label(self):
        bits = ", ".join("%s=%s" % (k, _short(v)) for k, v in sorted(self.p.items()))
        return "%s(%s)" % (self.key, bits)

    # helpers ------------------------------------------------------------

    def _blank(self, panel):
        return np.full((len(panel), len(self.symbols())), np.nan)

    def _park(self, W, panel, idx_off, invested):
        """Put 1 - invested into the off asset where it trades, else cash."""
        off = self.p.get("off")
        if off and off in panel.col:
            ok = np.isfinite(panel.close(off))
            W[:, idx_off] = np.where(ok, 1.0 - invested, 0.0)
        return W


def _short(v):
    if isinstance(v, (list, tuple)):
        return "[%s]" % ",".join(str(x) for x in v) if len(v) <= 4 else "[%d]" % len(v)
    if isinstance(v, dict):
        if len(v) > 4:
            return "{%d}" % len(v)
        return "{%s}" % ",".join("%s:%.3g" % (k, x) for k, x in v.items())
    return v


def period_ends(dates, freq="M", next_date=None):
    """True on the last trading day of each month (or quarter). The final row
    is an end only when `next_date`, the next trading session, falls in a new
    period: live, the newest bar is always the last row, so the bot passes
    the next session's date; a backtest has no row after its last one."""
    def key(x):
        m = np.asarray(x).astype("datetime64[M]").astype(int)
        return m // 3 if freq == "Q" else m
    k = key(dates)
    out = np.zeros(len(k), dtype=bool)
    if len(k) > 1:
        out[:-1] = k[1:] != k[:-1]
    if len(k) and next_date is not None:
        out[-1] = bool(key(np.datetime64(next_date, "D")) != k[-1])
    return out


def hold_between(decisions, ends, first_ok):
    """Weights decided at period ends, held until the next end. Rows before
    the first decision stay NaN."""
    W = np.full(decisions.shape, np.nan)
    cur = None
    for t in range(len(decisions)):
        if ends[t] and t >= first_ok and np.all(np.isfinite(decisions[t])):
            cur = decisions[t]
        if cur is not None:
            W[t] = cur
    return W


def inverse_vol(vols):
    """Weights proportional to 1/volatility over the finite, positive entries
    (equal risk from each asset when correlations are alike); 0 elsewhere."""
    vols = np.asarray(vols, dtype=np.float64)
    ok = np.isfinite(vols) & (vols > 0)
    w = np.zeros(len(vols))
    if ok.any():
        w[ok] = 1.0 / vols[ok]
        w /= w.sum()
    return w


def nyse_calendar(first_year, last_year):
    """numpy business-day calendar with NYSE's holidays."""
    hol = sorted(d for y in range(first_year, last_year + 1) for d in market_clock.holidays(y))
    return np.busdaycalendar(holidays=np.array(hol, dtype="datetime64[D]"))


def turn_of_month(dates, before, after):
    """For each date: is the NEXT NYSE session one of the last `before` or the
    first `after` sessions of its month? The exchange calendar is published in
    advance, so this uses no future prices. A weight decided at a close fills
    at the next open, so holding on these rows means holding on those days."""
    d = np.asarray(dates).astype("datetime64[D]")
    out = np.zeros(len(d), dtype=bool)
    if not len(d):
        return out
    years = d.astype("datetime64[Y]").astype(int) + 1970
    cal = nyse_calendar(int(years.min()) - 1, int(years.max()) + 1)
    day = np.timedelta64(1, "D")
    nxt = np.busday_offset(d + day, 0, roll="forward", busdaycal=cal)
    month = nxt.astype("datetime64[M]")
    nth = np.busday_count(month.astype("datetime64[D]"), nxt, busdaycal=cal) + 1
    month_end = (month + np.timedelta64(1, "M")).astype("datetime64[D]")
    left = np.busday_count(nxt + day, month_end, busdaycal=cal)
    return (nth <= int(after)) | (left < int(before))


# ---------------------------------------------------------------- strategies

class BuyHold(Strategy):
    key = "buy_hold"
    name = "Al ve Tut"
    summary = "Varlığı alır ve hep tutar. Karşılaştırma ölçütü."
    params = {"symbol": "SPY"}

    def symbols(self):
        return [self.p["symbol"]]

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        return np.where(np.isfinite(c), 1.0, np.nan)[:, None]


class FixedWeights(Strategy):
    """trader-copycat/trader-budget targets: hold these weights, rebalance on drift."""
    key = "fixed_weights"
    name = "Sabit Ağırlıklar (13F kopya)"
    summary = "Verilen ağırlıkları (ör. bir yatırımcının 13F portföyü) tutar, kayınca dengeler."
    params = {"weights": {"SPY": 1.0}}

    def symbols(self):
        return list(self.p["weights"])

    def weights(self, panel):
        syms = self.symbols()
        w = np.array([float(self.p["weights"][s]) for s in syms])
        tot = w.sum()
        if tot > 1.0:
            w = w / tot
        ok = np.all(np.isfinite(panel.c[:, [panel.col[s] for s in syms]]), axis=1)
        W = np.full((len(panel), len(syms)), np.nan)
        W[ok] = w
        return W


class SmaTrend(Strategy):
    key = "sma_trend"
    name = "Trend Filtresi (SMA)"
    summary = ("Fiyat N günlük ortalamanın üstündeyken varlığı tutar, altına inince "
               "hazine bonosu ETF'ine (BIL) geçer.")
    params = {"symbol": "SPY", "n": 200, "off": "BIL", "monthly": False}

    def symbols(self):
        return [self.p["symbol"], self.p["off"]]

    def warmup(self):
        return int(self.p["n"])

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        ma = ind.sma(c, self.p["n"])
        ready = np.isfinite(ma) & np.isfinite(c)
        on = (c > ma).astype(float)
        W = self._blank(panel)
        W[:, 0] = on
        self._park(W, panel, 1, on)
        W[~ready] = np.nan
        if self.p["monthly"]:
            first = int(np.argmax(ready)) if ready.any() else len(panel)
            ends = period_ends(panel.dates, next_date=panel.next_session)
            W = hold_between(np.where(ready[:, None], W, np.nan), ends, first)
        return W


class GoldenCross(Strategy):
    key = "golden_cross"
    name = "Altın Kesişim"
    summary = "Kısa ortalama uzun ortalamanın üstündeyken alır, altına inince BIL'e geçer."
    params = {"symbol": "SPY", "fast": 50, "slow": 200, "off": "BIL"}

    def symbols(self):
        return [self.p["symbol"], self.p["off"]]

    def warmup(self):
        return int(self.p["slow"])

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        f, s = ind.sma(c, self.p["fast"]), ind.sma(c, self.p["slow"])
        ready = np.isfinite(f) & np.isfinite(s)
        on = (f > s).astype(float)
        W = self._blank(panel)
        W[:, 0] = on
        self._park(W, panel, 1, on)
        W[~ready] = np.nan
        return W


class Rsi2(Strategy):
    key = "rsi2"
    name = "RSI(2) Geri Dönüş"
    summary = ("Uzun vadeli trend yukarıyken kısa süreli aşırı satışta alır (RSI(2) < giriş), "
               "fiyat kısa ortalamanın üstüne çıkınca satar. Larry Connors'ın kuralı.")
    params = {"symbol": "SPY", "entry": 10, "exit_n": 5, "trend_n": 200, "off": "BIL"}

    def symbols(self):
        return [self.p["symbol"], self.p["off"]]

    def warmup(self):
        return int(self.p["trend_n"])

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        r = ind.rsi(c, 2)
        trend = ind.sma(c, self.p["trend_n"])
        ex = ind.sma(c, self.p["exit_n"])
        ready = np.isfinite(trend) & np.isfinite(r) & np.isfinite(ex)
        on = np.zeros(len(c))
        inside = False
        for t in range(len(c)):
            if not ready[t]:
                inside = False
                continue
            if inside and c[t] > ex[t]:
                inside = False
            elif not inside and c[t] > trend[t] and r[t] < self.p["entry"]:
                inside = True
            on[t] = 1.0 if inside else 0.0
        W = self._blank(panel)
        W[:, 0] = on
        self._park(W, panel, 1, on)
        W[~ready] = np.nan
        return W


class DualMomentum(Strategy):
    key = "dual_momentum"
    name = "Çift Momentum (GEM)"
    summary = ("Her ay sonunda ABD (SPY) ile gelişmiş piyasalardan (EFA) son dönemde daha "
               "iyi olanı tutar; ABD hisseleri hazine bonosunu geçemiyorsa tahvile (AGG) geçer. "
               "Gary Antonacci'nin kuralı.")
    params = {"risk": ["SPY", "EFA"], "safe": "AGG", "cash": "BIL", "lookback": 12 * MONTH}

    def symbols(self):
        return list(self.p["risk"]) + [self.p["safe"]]

    def inputs(self):
        return self.symbols() + [self.p["cash"]]

    def warmup(self):
        return int(self.p["lookback"])

    def weights(self, panel):
        L = int(self.p["lookback"])
        risk = list(self.p["risk"])
        mom = np.column_stack([ind.momentum(panel.close(s), L) for s in risk])
        cash = self.p["cash"]
        cash_mom = ind.momentum(panel.close(cash), L) if cash in panel.col else np.zeros(len(panel))
        cash_mom = np.where(np.isfinite(cash_mom), cash_mom, 0.0)
        safe_ok = np.isfinite(panel.close(self.p["safe"]))
        ready = np.all(np.isfinite(mom), axis=1) & safe_ok
        dec = np.full((len(panel), len(risk) + 1), np.nan)
        for t in np.nonzero(ready)[0]:
            row = np.zeros(len(risk) + 1)
            if mom[t, 0] > cash_mom[t]:
                row[int(np.argmax(mom[t]))] = 1.0
            else:
                row[-1] = 1.0
            dec[t] = row
        first = int(np.argmax(ready)) if ready.any() else len(panel)
        return hold_between(dec, period_ends(panel.dates, next_date=panel.next_session), first)


class SectorRotation(Strategy):
    key = "sector_rotation"
    name = "Sektör Rotasyonu"
    summary = ("Her ay sonunda son dönemde en güçlü K sektör ETF'ini eşit ağırlıkla tutar; "
               "S&P 500 200 günlük ortalamasının altındaysa BIL'e geçer.")
    params = {"sectors": SECTORS, "k": 3, "lookback": 6 * MONTH, "trend_symbol": "SPY",
              "trend_n": 200, "off": "BIL"}

    def symbols(self):
        return list(self.p["sectors"]) + [self.p["off"]]

    def inputs(self):
        return self.symbols() + [self.p["trend_symbol"]]

    def warmup(self):
        return max(int(self.p["lookback"]), int(self.p["trend_n"]))

    def weights(self, panel):
        secs = list(self.p["sectors"])
        k = int(self.p["k"])
        mom = np.column_stack([ind.momentum(panel.close(s), self.p["lookback"]) for s in secs])
        tc = panel.close(self.p["trend_symbol"])
        tm = ind.sma(tc, self.p["trend_n"])
        off_ok = np.isfinite(panel.close(self.p["off"]))
        ready = np.isfinite(tm) & (np.sum(np.isfinite(mom), axis=1) >= k)
        dec = np.full((len(panel), len(secs) + 1), np.nan)
        for t in np.nonzero(ready)[0]:
            row = np.zeros(len(secs) + 1)
            if tc[t] > tm[t]:
                m = np.where(np.isfinite(mom[t]), mom[t], -np.inf)
                for j in np.argsort(-m, kind="stable")[:k]:
                    row[j] = 1.0 / k
            elif off_ok[t]:
                row[-1] = 1.0
            dec[t] = row
        first = int(np.argmax(ready)) if ready.any() else len(panel)
        return hold_between(dec, period_ends(panel.dates, next_date=panel.next_session), first)


class AssetRotation(Strategy):
    key = "asset_rotation"
    name = "Varlık Rotasyonu"
    summary = ("Her ay sonunda hisse, tahvil, altın, emtia ve gayrimenkul ETF'leri arasından "
               "1-3-6-12 aylık ortalama momentumu en güçlü K tanesini tutar; zayıf olanın "
               "payı BIL'e gider.")
    params = {"universe": ROTATION_UNIVERSE, "k": 3, "filter": "sma", "off": "BIL"}

    def symbols(self):
        return list(self.p["universe"]) + [self.p["off"]]

    def warmup(self):
        return 12 * MONTH

    def weights(self, panel):
        uni = list(self.p["universe"])
        k = int(self.p["k"])
        closes = [panel.close(s) for s in uni]
        score = np.column_stack([
            np.mean([ind.momentum(c, n * MONTH) for n in (1, 3, 6, 12)], axis=0) for c in closes])
        above = np.column_stack([c > ind.sma(c, 200) for c in closes])
        ma_ok = np.column_stack([np.isfinite(ind.sma(c, 200)) for c in closes])
        off_ok = np.isfinite(panel.close(self.p["off"]))
        avail = np.isfinite(score) & ma_ok
        ready = np.sum(avail, axis=1) >= k
        dec = np.full((len(panel), len(uni) + 1), np.nan)
        for t in np.nonzero(ready)[0]:
            row = np.zeros(len(uni) + 1)
            s = np.where(avail[t], score[t], -np.inf)
            for j in np.argsort(-s, kind="stable")[:k]:
                good = above[t, j] if self.p["filter"] == "sma" else score[t, j] > 0
                if good:
                    row[j] += 1.0 / k
                elif off_ok[t]:
                    row[-1] += 1.0 / k
            dec[t] = row
        first = int(np.argmax(ready)) if ready.any() else len(panel)
        return hold_between(dec, period_ends(panel.dates, next_date=panel.next_session), first)


class VolTargetTrend(Strategy):
    key = "vol_target"
    name = "Volatilite Hedefli Trend"
    summary = ("Trend yukarıyken (fiyat > N günlük ortalama) varlığı, oynaklığı hedefte "
               "tutacak oranda tutar; geri kalan BIL'de bekler.")
    params = {"symbol": "SPY", "n": 200, "target": 0.15, "vol_n": 20, "off": "BIL"}
    trade_on_change = False

    def symbols(self):
        return [self.p["symbol"], self.p["off"]]

    def warmup(self):
        return max(int(self.p["n"]), int(self.p["vol_n"]) + 1)

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        ma = ind.sma(c, self.p["n"])
        vol = ind.realized_vol(c, self.p["vol_n"])
        ready = np.isfinite(ma) & np.isfinite(vol) & (vol > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.clip(self.p["target"] / vol, 0.0, 1.0)
        w = np.where((c > ma) & ready, w, 0.0)
        W = self._blank(panel)
        W[:, 0] = w
        self._park(W, panel, 1, w)
        W[~ready] = np.nan
        return W


class RiskParity(Strategy):
    key = "risk_parity"
    name = "Risk Paritesi (ters oynaklık)"
    summary = ("Her ay sonunda hisse, tahvil, altın, emtia ve gayrimenkul ETF'lerini oynaklıklarıyla "
               "ters orantılı tutar; her varlık portföy riskine yaklaşık eşit katkı yapar. Kaldıraç "
               "kullanmaz, bu yüzden tahvil payı yüksektir.")
    params = {"universe": ASSET_CLASSES, "vol_n": 63, "min_assets": 3}

    def symbols(self):
        return list(self.p["universe"])

    def warmup(self):
        return int(self.p["vol_n"]) + 1

    def weights(self, panel):
        uni = list(self.p["universe"])
        vols = np.column_stack([ind.realized_vol(panel.close(s), self.p["vol_n"]) for s in uni])
        avail = np.isfinite(vols) & (vols > 0)
        ready = avail.sum(axis=1) >= int(self.p["min_assets"])
        dec = np.full((len(panel), len(uni)), np.nan)
        for t in np.nonzero(ready)[0]:
            dec[t] = inverse_vol(vols[t])
        return hold_between(dec, period_ends(panel.dates, next_date=panel.next_session), 0)


class TimeSeriesMomentum(Strategy):
    key = "tsmom"
    name = "Çoklu Varlık Trendi (TSMOM)"
    summary = ("Her ay sonunda her varlık sınıfının son dönem getirisine bakar: hazine bonosunu "
               "geçenleri oynaklıklarıyla ters orantılı ağırlıkla tutar, geçemeyenlerin payı BIL'e "
               "gider. Moskowitz, Ooi ve Pedersen'in (2012) zaman serisi momentumu, kaldıraçsız.")
    params = {"universe": ASSET_CLASSES, "lookback": 12 * MONTH, "vol_n": 63, "min_assets": 3,
              "off": "BIL"}

    def symbols(self):
        return list(self.p["universe"]) + [self.p["off"]]

    def warmup(self):
        return max(int(self.p["lookback"]), int(self.p["vol_n"]) + 1)

    def weights(self, panel):
        uni = list(self.p["universe"])
        n, L = len(uni), int(self.p["lookback"])
        closes = [panel.close(s) for s in uni]
        vols = np.column_stack([ind.realized_vol(c, self.p["vol_n"]) for c in closes])
        mom = np.column_stack([ind.momentum(c, L) for c in closes])
        off = self.p["off"]
        cash = ind.momentum(panel.close(off), L) if off in panel.col else np.zeros(len(panel))
        cash = np.where(np.isfinite(cash), cash, 0.0)
        off_ok = np.isfinite(panel.close(off)) if off in panel.col else np.zeros(len(panel), bool)
        avail = np.isfinite(vols) & (vols > 0) & np.isfinite(mom)
        ready = avail.sum(axis=1) >= int(self.p["min_assets"])
        dec = np.full((len(panel), n + 1), np.nan)
        for t in np.nonzero(ready)[0]:
            row = np.zeros(n + 1)
            w = inverse_vol(np.where(avail[t], vols[t], np.nan))
            row[:n] = np.where(avail[t] & (mom[t] > cash[t]), w, 0.0)
            if off_ok[t]:
                row[n] = max(0.0, 1.0 - row[:n].sum())
            dec[t] = row
        return hold_between(dec, period_ends(panel.dates, next_date=panel.next_session), 0)


class Gtaa(Strategy):
    key = "gtaa"
    name = "Faber GTAA (10 aylık ortalama)"
    summary = ("ABD ve dünya hisseleri, tahvil, emtia ve gayrimenkule eşit pay ayırır. Ay sonunda "
               "fiyatı 10 aylık ortalamasının altında kalan varlığın payı BIL'e geçer. Meb Faber'in "
               "(2007) taktik varlık dağılımı.")
    params = {"universe": FABER_UNIVERSE, "months": 10, "off": "BIL"}

    def symbols(self):
        return list(self.p["universe"]) + [self.p["off"]]

    def warmup(self):
        return (int(self.p["months"]) + 1) * MONTH

    def weights(self, panel):
        uni = list(self.p["universe"])
        n, m = len(uni), int(self.p["months"])
        closes = np.column_stack([panel.close(s) for s in uni])
        off = self.p["off"]
        off_ok = np.isfinite(panel.close(off)) if off in panel.col else np.zeros(len(panel), bool)
        ends = period_ends(panel.dates, next_date=panel.next_session)
        idx = np.nonzero(ends)[0]
        dec = np.full((len(panel), n + 1), np.nan)
        for j in range(m - 1, len(idx)):
            # the last m month-end closes, this month's included (Faber's 10-month SMA)
            window = closes[idx[j - m + 1:j + 1]]
            ok = np.all(np.isfinite(window), axis=0)
            if ok.sum() < (n + 1) // 2:
                continue
            t = idx[j]
            row = np.zeros(n + 1)
            above = ok & (closes[t] > np.where(ok, window.mean(axis=0), np.inf))
            row[:n] = np.where(above, 1.0 / n, 0.0)
            if off_ok[t]:
                row[n] = 1.0 - row[:n].sum()
            dec[t] = row
        return hold_between(dec, ends, 0)


class TurnOfMonth(Strategy):
    key = "turn_of_month"
    name = "Ay Dönümü Etkisi"
    summary = ("Ayın son N ve yeni ayın ilk M işlem gününde SPY tutar, diğer günlerde BIL'de "
               "bekler. McConnell ve Xu'nun (2008) belgelediği takvim etkisi; son yıllarda "
               "zayıfladığını gösteren çalışmalar da var.")
    params = {"symbol": "SPY", "before": 1, "after": 3, "off": "BIL"}

    def symbols(self):
        return [self.p["symbol"], self.p["off"]]

    def weights(self, panel):
        c = panel.close(self.p["symbol"])
        on = turn_of_month(panel.dates, self.p["before"], self.p["after"]).astype(float)
        W = self._blank(panel)
        W[:, 0] = on
        self._park(W, panel, 1, on)
        W[~np.isfinite(c)] = np.nan
        return W


class Ensemble(Strategy):
    key = "ensemble"
    name = "Strateji Karması"
    summary = ("Birkaç stratejiyi sabit paylarla birlikte çalıştırır (varsayılan: yarı Volatilite "
               "Hedefli Trend, yarı Faber GTAA). Farklı varlıklar ve kurallar birbirinin kötü "
               "dönemlerini yumuşatır. Pay yazımı: strateji_anahtarı=pay.")
    params = {"parts": {"vol_target": 0.5, "gtaa": 0.5}}

    def __init__(self, **kw):
        super().__init__(**kw)
        parts = {}
        for k, v in dict(self.p["parts"]).items():
            k = str(k).strip().lower()
            if float(v) > 0:
                parts[k] = parts.get(k, 0.0) + float(v)
        bad = sorted(k for k in parts if k not in REGISTRY or k in ("ensemble", "fixed_weights"))
        if not parts or bad:
            raise ValueError("ensemble: geçersiz parça(lar) %s; seçenekler: %s" % (
                ", ".join(bad) or "(boş)",
                ", ".join(k for k in REGISTRY if k not in ("ensemble", "fixed_weights"))))
        tot = sum(parts.values())
        self.p["parts"] = {k: v / tot for k, v in parts.items()}
        self.members = [(REGISTRY[k](), share) for k, share in self.p["parts"].items()]
        # one continuous member makes the blend continuous: trade on drift only
        self.trade_on_change = all(m.trade_on_change for m, _ in self.members)

    def symbols(self):
        return list(dict.fromkeys(s for m, _ in self.members for s in m.symbols()))

    def inputs(self):
        return list(dict.fromkeys(s for m, _ in self.members for s in m.inputs()))

    def warmup(self):
        return max(m.warmup() for m, _ in self.members)

    def weights(self, panel):
        syms = self.symbols()
        col = {s: i for i, s in enumerate(syms)}
        W = np.zeros((len(panel), len(syms)))
        ready = np.ones(len(panel), dtype=bool)
        for m, share in self.members:
            Wm = m.weights(panel)
            ready &= np.all(np.isfinite(Wm), axis=1)
            for j, s in enumerate(m.symbols()):
                W[:, col[s]] += share * np.nan_to_num(Wm[:, j])
        W[~ready] = np.nan
        return W


REGISTRY = {cls.key: cls for cls in (BuyHold, FixedWeights, SmaTrend, GoldenCross, Rsi2,
                                     DualMomentum, SectorRotation, AssetRotation,
                                     VolTargetTrend, Gtaa, TimeSeriesMomentum, RiskParity,
                                     TurnOfMonth, Ensemble)}


def create(key, **params):
    if key not in REGISTRY:
        raise ValueError("unknown strategy %r" % key)
    return REGISTRY[key](**params)
