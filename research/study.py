"""Strategy study: which strategy should the bot run?

    python -m research.study            # writes research/results.json and REPORT.md

Protocol, fixed before any result was looked at:

1. Data: daily split and dividend adjusted prices from Yahoo Finance
   (research/data, fetched by research/fetch_data.py). Before BIL existed
   (2007-05-30) the T-bill sleeve is spliced from SHY's returns.
2. Three windows, each starting from cash:
     train       2005-01-03 .. 2015-12-31  (includes 2008)
     validation  2016-01-04 .. 2022-12-30  (2018 Q4, 2020 crash, 2022 bear)
     test        2023-01-03 .. last bar    (held out: looked at once, at the end)
3. Costs: 5 bps of every traded dollar. Fills at the next day's open.
4. Each family's parameters: the grid point with the best TRAIN Sharpe
   (excess over T-bills).
5. The winning family: best VALIDATION Sharpe among families whose chosen
   point (a) did not draw down deeper than SPY buy-and-hold in validation,
   (b) traded at least 10 times in validation, and (c) is not a lone lucky
   grid point: the family's median train Sharpe is at least 75% of the
   chosen point's.
6. The test window is reported for the winner and the benchmarks only, and
   is never used to choose anything. If no family passes step 5, the bot's
   default is SPY buy-and-hold.

Round 2 (2026-10-29): five families from the research literature were added,
their grids written before they were run: Faber's GTAA, time-series momentum,
risk parity, the turn of the month, and a blend of strategies. Steps 4-6 are
unchanged. The test window had been looked at once, in round 1, for the first
seven families, so for them it is no longer untouched; it is still never used
to choose. Also reported now: the winner's deflated Sharpe ratio over every
grid point tried, a walk-forward run of every family, a block-bootstrap range
for the next five years, and what followed each market regime.
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

from traderbot import analysis, regime
from traderbot import strategies as st
from traderbot.backtest import build_panel, metrics, run_backtest
from traderbot.data.bars import Bars

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOWS = {
    "train": ("2005-01-03", "2015-12-31"),
    "validation": ("2016-01-04", "2022-12-30"),
    "test": ("2023-01-03", None),
}
COST_BPS = 5.0
BAND = 0.05
M = st.MONTH

GRID = {
    "sma_trend": [dict(n=n, monthly=m) for n in (100, 150, 200, 250) for m in (False, True)],
    "golden_cross": [dict(fast=f, slow=s) for f, s in ((20, 100), (50, 150), (50, 200), (100, 250))],
    "rsi2": [dict(entry=e, exit_n=x) for e in (5, 10, 15) for x in (5, 10)],
    "dual_momentum": [dict(lookback=m * M) for m in (6, 9, 12)],
    "sector_rotation": [dict(k=k, lookback=l * M) for k in (2, 3, 4) for l in (3, 6, 12)],
    "asset_rotation": [dict(k=k, filter=f) for k in (2, 3, 4) for f in ("sma", "abs")],
    "vol_target": [dict(target=v, n=n) for v in (0.10, 0.15, 0.20) for n in (150, 200)],
    # round 2
    "gtaa": [dict(months=m) for m in (6, 8, 10, 12)],
    "tsmom": [dict(lookback=m * M, vol_n=v) for m in (3, 6, 12) for v in (21, 63)],
    "risk_parity": [dict(vol_n=v) for v in (21, 63, 126)],
    "turn_of_month": [dict(before=b, after=a) for b in (1, 2) for a in (2, 3, 4)],
    "ensemble": [dict(parts=p) for p in ({"vol_target": 0.5, "gtaa": 0.5},
                                         {"vol_target": 0.5, "tsmom": 0.5},
                                         {"vol_target": 0.5, "risk_parity": 0.5},
                                         {"vol_target": 1, "gtaa": 1, "tsmom": 1})],
}
WALK = dict(train_years=5, test_years=1)
MC_YEARS, MC_PATHS = 5, 5000
BENCHMARKS = {
    "SPY al-tut": ("buy_hold", {"symbol": "SPY"}),
    "60/40 (SPY/AGG)": ("fixed_weights", {"weights": {"SPY": 0.6, "AGG": 0.4}}),
}


def load_bars(data_dir):
    bars = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.csv.gz"))):
        sym = os.path.basename(path).split(".")[0]
        bars[sym] = Bars.load_csv(path, sym, gmtoffset=-18000)
    return bars


def splice_cash(bars, cash="BIL", proxy="SHY"):
    """Extend `cash` back in time with `proxy`'s daily returns, scaled to meet
    `cash`'s first bar. Prices are adjusted closes (OHLC all set to it)."""
    c, p = bars[cash].adjusted(), bars[proxy].adjusted()
    first = c.t[0]
    before = p.t < first
    if not before.any():
        return bars
    k = c.c[0] / p.c[np.nonzero(p.t >= first)[0][0]]
    t = np.concatenate([p.t[before], c.t])
    px = np.concatenate([p.c[before] * k, c.c])
    vol = np.concatenate([np.zeros(before.sum()), c.v])
    out = dict(bars)
    out[cash] = Bars(cash, "1d", t, px, px, px, px, vol, px, c.gmtoffset)
    return out


def evaluate(strategy, panel, rf):
    W = strategy.weights(panel)
    res = {}
    for name, (start, end) in WINDOWS.items():
        r = run_backtest(panel, W, strategy.symbols(), start, end, cost_bps=COST_BPS,
                         band=BAND, trade_on_change=strategy.trade_on_change)
        res[name] = r.metrics(rf)
    return res


def run(data_dir, out_dir):
    bars = splice_cash(load_bars(data_dir))
    panel = build_panel(bars, calendar_symbol="SPY")
    bil = panel.close("BIL")
    rf = np.concatenate([[np.nan], bil[1:] / bil[:-1] - 1.0])
    last = str(panel.dates[-1])

    results = {"protocol": __doc__, "last_bar": last, "cost_bps": COST_BPS, "band": BAND,
               "windows": {k: [v[0], v[1] or last] for k, v in WINDOWS.items()},
               "benchmarks": {}, "families": {}}
    for label, (key, params) in BENCHMARKS.items():
        results["benchmarks"][label] = {"key": key, "params": params,
                                        "metrics": evaluate(st.create(key, **params), panel, rf)}
    spy_valid_dd = results["benchmarks"]["SPY al-tut"]["metrics"]["validation"]["max_dd"]

    for fam, grid in GRID.items():
        rows = []
        for params in grid:
            s = st.create(fam, **params)
            rows.append({"params": params, "label": s.label(),
                         "metrics": evaluate(s, panel, rf)})
            print("  %-60s train %5.2f  valid %5.2f" % (
                s.label()[:60], rows[-1]["metrics"]["train"]["sharpe_excess"],
                rows[-1]["metrics"]["validation"]["sharpe_excess"]), flush=True)
        train_sh = np.array([r["metrics"]["train"]["sharpe_excess"] for r in rows])
        best = int(np.argmax(train_sh))
        chosen = rows[best]
        v = chosen["metrics"]["validation"]
        median = float(np.median(train_sh))
        checks = {
            "drawdown_ok": v["max_dd"] >= spy_valid_dd,
            "trades_ok": v["trades"] >= 10,
            "robust_ok": train_sh[best] > 0 and median >= 0.75 * train_sh[best],
        }
        results["families"][fam] = {
            "name": st.REGISTRY[fam].name, "grid": rows, "chosen": best,
            "train_sharpe_median": median, "checks": checks,
            "qualifies": all(checks.values()),
        }

    ok = {f: d for f, d in results["families"].items() if d["qualifies"]}
    if ok:
        winner = max(ok, key=lambda f: ok[f]["grid"][ok[f]["chosen"]]["metrics"]["validation"]
                     ["sharpe_excess"])
        params = ok[winner]["grid"][ok[winner]["chosen"]]["params"]
    else:
        winner, params = "buy_hold", {"symbol": "SPY"}
    results["winner"] = {"key": winner, "params": params}

    print("reliability, walk-forward, Monte Carlo, regimes...", flush=True)
    results["reliability"] = reliability(winner, params, panel, rf, results)
    results["walk_forward"] = walk_forward_all(panel, rf)
    results["monte_carlo"] = monte_carlo(winner, params, panel)
    results["regimes"] = regime.conditional_stats(panel, horizon=21, start=WINDOWS["train"][0])

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, default=_json_default)
        fh.write("\n")
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(report(results))
    return results


def _excess_returns(strategy, W, panel, rf, start, end):
    r = run_backtest(panel, W, strategy.symbols(), start, end, cost_bps=COST_BPS, band=BAND,
                     trade_on_change=strategy.trade_on_change)
    _, eq = r.window()
    cash = np.nan_to_num(rf[r.start:r.end + 1][1:])
    ok = np.isfinite(eq)
    return (eq[ok][1:] / eq[ok][:-1] - 1.0) - cash[ok[1:]]


def reliability(key, params, panel, rf, results):
    """PSR in each window, the deflated Sharpe ratio of the validation pick
    over every grid point tried, and the minimum track record length."""
    trials = [analysis.daily(row["metrics"]["validation"]["sharpe_excess"])
              for f in results["families"].values() for row in f["grid"]]
    out = {"trials": len(trials), "rows": {}}
    for label, (k, p) in [("winner", (key, params)), ("SPY al-tut", ("buy_hold", {"symbol": "SPY"}))]:
        s = st.create(k, **p)
        W = s.weights(panel)
        rows = {}
        for win in ("train", "validation", "test"):
            start, end = WINDOWS[win]
            ex = _excess_returns(s, W, panel, rf, start, end)
            sr, skew, kurt = analysis.moments(ex)
            rows[win] = {"sharpe": analysis.annual(sr), "skew": skew, "kurt": kurt,
                         "psr": analysis.probabilistic_sharpe(ex),
                         "min_trl_years": analysis.min_track_record(ex) / 252.0}
        ex = _excess_returns(s, W, panel, rf, *WINDOWS["validation"])
        dsr, sr0 = analysis.deflated_sharpe(ex, trials)
        rows["validation"].update(dsr=dsr, sr0=analysis.annual(sr0))
        out["rows"][label] = rows
    return out


def walk_forward_all(panel, rf):
    """Every family re-choosing its parameters each year from the 5 years
    before, against SPY over the same out-of-sample span."""
    out = {"settings": WALK, "families": {}}
    span = None
    for fam, grid in GRID.items():
        wf = analysis.walk_forward(fam, grid, panel, start=WINDOWS["train"][0], rf=rf,
                                   cost_bps=COST_BPS, band=BAND, **WALK)
        out["families"][fam] = {"name": st.REGISTRY[fam].name, "metrics": wf["metrics"],
                                "train_sharpe": wf["train_sharpe"],
                                "efficiency": wf["efficiency"],
                                "picks": [f["params"] for f in wf["folds"]],
                                "folds": len(wf["folds"])}
        span = (str(wf["dates"][0]), str(wf["dates"][-1]))
        print("  walk-forward %-16s oos sharpe %5.2f" % (fam, wf["metrics"]["sharpe_excess"]),
              flush=True)
    spy = st.create("buy_hold", symbol="SPY")
    r = run_backtest(panel, spy.weights(panel), ["SPY"], span[0], span[1], cost_bps=COST_BPS)
    out["spy"] = r.metrics(rf)
    out["span"] = span
    return out


def monte_carlo(key, params, panel):
    """Block bootstrap of 2005-today daily returns: the range of five-year
    outcomes for the winner and for SPY."""
    out = {"years": MC_YEARS, "paths": MC_PATHS, "rows": {}}
    for label, (k, p) in [("winner", (key, params)), ("SPY al-tut", ("buy_hold", {"symbol": "SPY"}))]:
        s = st.create(k, **p)
        r = run_backtest(panel, s.weights(panel), s.symbols(), WINDOWS["train"][0], None,
                         cost_bps=COST_BPS, band=BAND, trade_on_change=s.trade_on_change)
        _, eq = r.window()
        mc = analysis.bootstrap(analysis.returns(eq), MC_YEARS * 252, n_paths=MC_PATHS, seed=2026)
        mc.pop("fan")
        out["rows"][label] = mc
    return out


def _json_default(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    raise TypeError(type(x))


# ---------------------------------------------------------------- report

def pct(x, digits=1):
    return "—" if x is None else ("%+.*f%%" % (digits, 100 * x)).replace("+-", "-")


def num(x, digits=2):
    return "—" if x is None else "%.*f" % (digits, x)


def row(label, m):
    return "| %s | %s | %s | %s | %s | %s | %s |" % (
        label, pct(m["cagr"]), pct(m["vol"]), num(m["sharpe_excess"]), pct(m["max_dd"]),
        num(m["calmar"]), m["trades"])


HEAD = ("| Strateji | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Calmar | İşlem |\n"
        "|---|---|---|---|---|---|---|")


def report(res):
    w = res["winner"]
    fams = res["families"]
    out = []
    out.append("# Strateji araştırması\n")
    out.append("Bu rapor `python -m research.study` ile üretildi. Veri: Yahoo Finance günlük "
               "fiyatları (bölünme ve temettü düzeltilmiş), son bar %s. Her işlemde %.0f baz puan "
               "maliyet, emirler ertesi günün açılışında dolar. Getiriler geçmişe aittir; "
               "gelecekte aynısının olacağını göstermez.\n" % (res["last_bar"], res["cost_bps"]))
    out.append("## Kural (sonuçlara bakmadan önce yazıldı)\n")
    out.append("1. Her ailenin parametresi **eğitim** döneminde (2005–2015) en iyi Sharpe'a göre seçilir.\n"
               "2. Kazanan aile, **doğrulama** döneminde (2016–2022) en iyi Sharpe'a sahip olandır; ancak "
               "SPY al-tut'tan daha derin düşüş yapmamalı, en az 10 işlem yapmalı ve tek bir şanslı "
               "parametreye dayanmamalı (ailenin medyan eğitim Sharpe'ı seçilenin en az %75'i).\n"
               "3. **Test** dönemi (2023–bugün) seçimde hiç kullanılmadı; sadece sonda raporlandı.\n"
               "4. Hiçbir aile geçemezse bot SPY al-tut ile başlar.\n"
               "5. **2. tur (29.10.2026):** literatürden beş aile eklendi (Faber GTAA, zaman serisi "
               "momentumu, risk paritesi, ay dönümü etkisi, strateji karması). Izgaraları sonuçlara "
               "bakmadan yazıldı; 1-4. kurallar değişmedi. İlk yedi ailenin test dönemine 1. turda bir "
               "kez bakılmıştı.\n")
    if w["key"] in fams:
        f = fams[w["key"]]
        chosen = f["grid"][f["chosen"]]
        out.append("## Sonuç: %s\n" % f["name"])
        out.append("Seçilen parametreler: `%s`\n" % chosen["label"])
    else:
        chosen = None
        out.append("## Sonuç: hiçbir aile kuralı geçemedi, varsayılan SPY al-tut\n")
    spy = res["benchmarks"]["SPY al-tut"]["metrics"]
    for win, title in (("test", "Test dönemi (seçimde kullanılmadı)"),
                       ("validation", "Doğrulama dönemi"), ("train", "Eğitim dönemi")):
        a, b = res["windows"][win]
        out.append("### %s: %s – %s\n" % (title, a, b))
        out.append(HEAD)
        if chosen is not None:
            out.append(row("**%s**" % fams[w["key"]]["name"], chosen["metrics"][win]))
        for label, bm in res["benchmarks"].items():
            out.append(row(label, bm["metrics"][win]))
        out.append("")
    out.append("## Tüm aileler (seçilen parametreyle)\n")
    out.append("| Aile | Parametre | Eğitim Sharpe | Doğrulama Sharpe | Doğrulama düşüş | "
               "Doğrulama işlem | Kurallar |\n|---|---|---|---|---|---|---|")
    for key, f in sorted(fams.items(), key=lambda kv: -kv[1]["grid"][kv[1]["chosen"]]
                         ["metrics"]["validation"]["sharpe_excess"]):
        c = f["grid"][f["chosen"]]
        flags = ", ".join(k.replace("_ok", "") for k, v in f["checks"].items() if not v)
        out.append("| %s | `%s` | %s | %s | %s | %s | %s |" % (
            f["name"], c["label"].split("(", 1)[1].rstrip(")"),
            num(c["metrics"]["train"]["sharpe_excess"]),
            num(c["metrics"]["validation"]["sharpe_excess"]),
            pct(c["metrics"]["validation"]["max_dd"]), c["metrics"]["validation"]["trades"],
            "geçti" if f["qualifies"] else "kaldı: " + flags))
    out.append("\nSPY al-tut doğrulama düşüşü: %s.\n" % pct(spy["validation"]["max_dd"]))
    if chosen is not None:
        out.append("## Yıllık getiriler: %s ve SPY\n" % fams[w["key"]]["name"])
        out.append("| Yıl | %s | SPY |\n|---|---|---|" % fams[w["key"]]["name"])
        years = {}
        for win in ("train", "validation", "test"):
            for y, v in chosen["metrics"][win]["yearly"].items():
                years.setdefault(y, [None, None])[0] = v
            for y, v in spy[win]["yearly"].items():
                years.setdefault(y, [None, None])[1] = v
        for y in sorted(years):
            out.append("| %s | %s | %s |" % (y, pct(years[y][0]), pct(years[y][1])))
        out.append("")
    out.append("## Test dönemi, tüm aileler (yalnızca bilgi için)\n")
    out.append("Seçim bu tabloya bakılmadan yapıldı. Buradan strateji seçmek, test dönemini "
               "seçimde kullanmak olur ve geçmişe fazla uyum riskini geri getirir.\n")
    out.append(HEAD)
    for key, f in sorted(fams.items(), key=lambda kv: -kv[1]["grid"][kv[1]["chosen"]]
                         ["metrics"]["test"]["sharpe_excess"]):
        out.append(row(f["name"], f["grid"][f["chosen"]]["metrics"]["test"]))
    out.append(row("SPY al-tut", spy["test"]))
    out.append("")
    name = fams[w["key"]]["name"] if w["key"] in fams else "SPY al-tut"
    if "reliability" in res:
        out.extend(reliability_md(res["reliability"], name))
    if "walk_forward" in res:
        out.extend(walk_md(res["walk_forward"]))
    if "monte_carlo" in res:
        out.extend(mc_md(res["monte_carlo"], name))
    if "regimes" in res:
        out.extend(regimes_md(res["regimes"]))
    out.append("## Bilinen sınırlar\n")
    out.append("- Geçmiş performans geleceği garanti etmez. Bu stratejiler yayınlandıktan sonra da "
               "çalıştı mı diye bakmak için test dönemi ayrıldı, ama 3-4 yıl kısa bir süre.\n"
               "- Vergiler ve döviz kuru (TL/USD) hesaba katılmadı. Temettüler düzeltilmiş fiyatlarla "
               "dahil; gerçekte temettülerden stopaj kesilir.\n"
               "- 2007 öncesinde BIL yoktu; o dönemde nakit kolu SHY'nin getirisiyle dolduruldu.\n"
               "- Bazı ETF'ler (GLD, DBC, VNQ) 2004-2006'da başladı; varlık rotasyonu o yıllarda daha "
               "az varlıktan seçti.\n"
               "- VIX3M 2006'dan, HYG 2007'den başlar; o rejim göstergeleri daha kısa dönemi kapsar.\n"
               "- 2. turda eklenen aileler için test dönemi ilk kez açıldı; ilk yedi aile için ise "
               "test dönemine 1. turda bir kez bakılmıştı.\n")
    return "\n".join(out) + "\n"


def years_txt(x):
    return "∞" if not np.isfinite(x) else ("%.0f yıl" % x if x >= 10 else "%.1f yıl" % x)


def reliability_md(rel, name):
    out = ["## Güvenilirlik: kısa geçmiş ve seçim yanlılığı\n",
           "Bir backtest'in Sharpe oranı iki nedenle gerçeğinden iyi görünür: geçmiş kısadır ve en "
           "iyisi çok sayıda denemenin arasından seçilmiştir. **Olasılıksal Sharpe (PSR)**, gerçek "
           "Sharpe'ın sıfırdan büyük olma olasılığıdır; getirilerin çarpıklığını ve basıklığını "
           "hesaba katar. **Deflated Sharpe (DSR)**, aynı olasılığı, denenen tüm ayarların en "
           "şanslısının şans eseri alacağı Sharpe'a karşı ölçer (Bailey ve López de Prado, 2012 ve "
           "2014). Bu çalışmada **%d ayar** denendi; araştırmacının gayriresmî denemeleri sayılmadığı "
           "için DSR iyimser tarafta kalır. Son sütun, Sharpe'ın sıfırdan büyük olduğuna %%95 güvenle "
           "karar vermek için gereken getiri geçmişidir.\n" % rel["trials"],
           "| Strateji | Dönem | Sharpe (BIL üstü) | PSR (>0) | DSR | %95 güven için gereken süre |",
           "|---|---|---|---|---|---|"]
    for label, rows in rel["rows"].items():
        shown = "**%s**" % name if label == "winner" else label
        for win, title in (("train", "Eğitim"), ("validation", "Doğrulama"), ("test", "Test")):
            r = rows[win]
            dsr = ("%.0f%% (eşik Sharpe %.2f)" % (100 * r["dsr"], r["sr0"])) if "dsr" in r else "—"
            out.append("| %s | %s | %s | %.0f%% | %s | %s |" % (
                shown, title, num(r["sharpe"]), 100 * r["psr"], dsr, years_txt(r["min_trl_years"])))
    out.append("")
    return out


def walk_md(wf):
    a, b = wf["span"]
    out = ["## İleri yürüyüş: her yıl parametreyi yeniden seçmek\n",
           "Her yılın başında ailenin parametresi önceki %d yılın en iyi Sharpe'ına göre seçildi ve "
           "sonraki %d yıl bu parametreyle işlem yapıldı; yıllar uç uca eklendi (%s – %s). Bu eğri "
           "geri görüş içermez: her karar, verildiği gün bilinen veriyle verildi. **Verim** = örnek "
           "dışı Sharpe / eğitim Sharpe'ı; 0.5'in altı, geçmişte iyi görünen parametrelerin geleceğe "
           "pek taşınmadığını gösterir.\n" % (wf["settings"]["train_years"],
                                               wf["settings"]["test_years"], a, b),
           "| Aile | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Eğitim Sharpe | Verim |",
           "|---|---|---|---|---|---|---|"]
    fams = sorted(wf["families"].values(), key=lambda f: -f["metrics"]["sharpe_excess"])
    for f in fams:
        m = f["metrics"]
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            f["name"], pct(m["cagr"]), pct(m["vol"]), num(m["sharpe_excess"]), pct(m["max_dd"]),
            num(f["train_sharpe"]), num(f["efficiency"]) if np.isfinite(f["efficiency"]) else "—"))
    m = wf["spy"]
    out.append("| SPY al-tut (aynı dönem) | %s | %s | %s | %s | — | — |" % (
        pct(m["cagr"]), pct(m["vol"]), num(m["sharpe_excess"]), pct(m["max_dd"])))
    out.append("")
    return out


def mc_md(mc, name):
    out = ["## Monte Carlo: önümüzdeki %d yıl için olası aralık\n" % mc["years"],
           "2005'ten bugüne günlük getiriler, ortalama 21 günlük bloklar halinde rastgele yeniden "
           "dizildi (durağan blok bootstrap, Politis ve Romano 1994); %d yol. Bu, geçmişin aynen "
           "tekrarlanacağını değil, geçmişteki iniş çıkışlar başka bir sırayla gelseydi neler "
           "olabileceğini gösterir. Geçmişte görülmemiş bir kriz bu aralığın dışına çıkabilir.\n"
           % mc["paths"],
           "| Strateji | Yıllık getiri: kötü (%5) | orta | iyi (%95) | En büyük düşüş: orta | "
           "kötü (%5) | Zararla bitirme olasılığı | %20'den derin düşüş olasılığı |",
           "|---|---|---|---|---|---|---|---|"]
    for label, r in mc["rows"].items():
        shown = "**%s**" % name if label == "winner" else label
        c, d = r["cagr"], r["max_dd"]
        out.append("| %s | %s | %s | %s | %s | %s | %.0f%% | %.0f%% |" % (
            shown, pct(c[5]), pct(c[50]), pct(c[95]), pct(d[50]), pct(d[5]),
            100 * r["p_loss"], 100 * r["p_dd"][0.2]))
    out.append("")
    return out


def regimes_md(reg):
    h = reg["horizon"]
    out = ["## Piyasa rejimleri: sonraki 1 ayda ne oldu? (SPY)\n",
           "Her gösterge için, göstergenin o durumda olduğu günlerden sonraki %d işlem gününde SPY'ın "
           "getirisi ve oynaklığı. Uygulamadaki **Piyasa** sekmesi aynı göstergeleri bugünün "
           "verisiyle gösterir. Pencereler çakıştığı için gün sayısı bağımsız gözlem sayısını abartır; "
           "farkların bir kısmı tesadüf olabilir.\n" % h]
    a = reg["all"]
    out.append("Tüm günler: ortalama aylık getiri %s, yükselen ay oranı %.0f%%, kötü ay (%%5) %s, "
               "sonraki oynaklık %s.\n" % (pct(a["mean"], 2), 100 * a["up"], pct(a["p5"]),
                                           pct(a["vol"])))
    for it in reg["indicators"]:
        out.append("### %s (veri %s'den)\n" % (it["name"], it["since"]))
        out.append("| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | "
                   "Sonraki oynaklık |\n|---|---|---|---|---|---|")
        for r in it["rows"]:
            s = r["stats"]
            if not s:
                out.append("| %s | (20 günden az) | | | | |" % r["label"])
                continue
            out.append("| %s | %.0f%% | %s | %.0f%% | %s | %s |" % (
                r["label"], 100 * s["share"], pct(s["mean"], 2), 100 * s["up"], pct(s["p5"]),
                pct(s["vol"])))
        out.append("")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the strategy study")
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    ap.add_argument("--out", default=HERE)
    args = ap.parse_args(argv)
    res = run(args.data, args.out)
    w = res["winner"]
    print("winner:", w["key"], w["params"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
