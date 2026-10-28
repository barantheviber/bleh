"""Download daily OHLCV history for the strategy study.

Runs in GitHub Actions, where Yahoo Finance is reachable:

    python -m research.fetch_data --tickers research/tickers.txt --out research/data

Writes research/data/<TICKER>.csv.gz (with the split and dividend adjusted
close) and research/data/manifest.json. Yahoo is the source; Stooq is tried
only if Yahoo fails for a ticker, and the manifest records which one served it.
"""

import argparse
import datetime as _dt
import io
import json
import os
import sys
import time
import urllib.request

from traderbot.data.bars import Bars
from traderbot.data.yahoo import UA, DataError, YahooClient


def read_tickers(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0]
            out.extend(t.strip().upper() for t in line.split() if t.strip())
    return list(dict.fromkeys(out))


def from_stooq(ticker, timeout=30):
    """Stooq's free daily CSV. Its prices are already split adjusted; there is
    no separate adjusted close, so adj is left empty and the study says so."""
    url = "https://stooq.com/q/d/l/?s=%s.us&i=d" % ticker.lower().replace("-", ".")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace")
    if not text.startswith("Date,"):
        raise DataError("stooq: %s" % text.strip()[:80])
    rows = text.strip().splitlines()[1:]
    csv = io.StringIO()
    csv.write("date,open,high,low,close,volume\n")
    for r in rows:
        parts = r.split(",")
        if len(parts) >= 6 and parts[1]:
            csv.write(",".join(parts[:6]) + "\n")
    return Bars.from_csv_text(csv.getvalue(), ticker, "1d", 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tickers", required=True, help="text file, tickers separated by spaces")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--pause", type=float, default=0.6, help="seconds between tickers")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    client = YahooClient(timeout=30, retries=3)
    manifest = {"fetched_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tickers": {}}
    failed = []
    for i, t in enumerate(read_tickers(args.tickers)):
        if i:
            time.sleep(args.pause)
        source, bars, err = None, None, None
        try:
            bars, _ = client.chart(t, "1d", range_="max")
            source = "yahoo"
        except DataError as exc:
            err = str(exc)
            try:
                bars = from_stooq(t)
                source = "stooq"
            except Exception as exc2:  # report both failures, keep going
                err = "%s | stooq: %s" % (err, exc2)
        if bars is None or not len(bars):
            print("FAIL %-6s %s" % (t, err), flush=True)
            failed.append(t)
            continue
        bars.save_csv(os.path.join(args.out, "%s.csv.gz" % t))
        manifest["tickers"][t] = {"source": source, "rows": len(bars),
                                  "first": bars.date_str(0), "last": bars.date_str(-1),
                                  "adjusted": bars.adj is not None}
        print("ok   %-6s %-5s %5d rows  %s .. %s" % (t, source, len(bars), bars.date_str(0),
                                                    bars.date_str(-1)), flush=True)
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("%d ok, %d failed %s" % (len(manifest["tickers"]), len(failed), " ".join(failed)))
    return 1 if failed and not manifest["tickers"] else 0


if __name__ == "__main__":
    sys.exit(main())
