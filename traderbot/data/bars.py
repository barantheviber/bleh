"""OHLCV bar container shared by the charts, the backtester and the bot."""

import csv
import datetime as _dt
import gzip
import io

import numpy as np

FIELDS = ("open", "high", "low", "close", "volume")


class Bars(object):
    """Bars for one symbol at one interval, oldest first.

    t is the bar start in unix seconds (UTC). gmtoffset is the exchange's
    offset from UTC in seconds, used only to turn t into local dates.
    adj is the split and dividend adjusted close (daily bars only, else None).
    """

    def __init__(self, symbol, interval, t, o, h, l, c, v, adj=None, gmtoffset=0):
        self.symbol = symbol
        self.interval = interval
        self.t = np.asarray(t, dtype=np.int64)
        self.o = np.asarray(o, dtype=np.float64)
        self.h = np.asarray(h, dtype=np.float64)
        self.l = np.asarray(l, dtype=np.float64)
        self.c = np.asarray(c, dtype=np.float64)
        self.v = np.asarray(v, dtype=np.float64)
        self.adj = None if adj is None else np.asarray(adj, dtype=np.float64)
        self.gmtoffset = int(gmtoffset or 0)
        n = len(self.t)
        for name in ("o", "h", "l", "c", "v"):
            if len(getattr(self, name)) != n:
                raise ValueError("%s: %s has %d values, t has %d"
                                 % (symbol, name, len(getattr(self, name)), n))
        if self.adj is not None and len(self.adj) != n:
            raise ValueError("%s: adj has %d values, t has %d" % (symbol, len(self.adj), n))

    def __len__(self):
        return len(self.t)

    def __repr__(self):
        span = ""
        if len(self):
            span = " %s..%s" % (self.date_str(0), self.date_str(-1))
        return "<Bars %s %s n=%d%s>" % (self.symbol, self.interval, len(self), span)

    # ------------------------------------------------------------ dates

    def local_datetime(self, i):
        return _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=int(self.t[i]) + self.gmtoffset)

    def date_str(self, i):
        return self.local_datetime(i).strftime("%Y-%m-%d")

    def dates(self):
        """Local calendar dates as numpy datetime64[D]."""
        return ((self.t + self.gmtoffset) // 86400).astype("datetime64[D]")

    # ------------------------------------------------------------ transforms

    def copy(self):
        return Bars(self.symbol, self.interval, self.t.copy(), self.o.copy(), self.h.copy(),
                    self.l.copy(), self.c.copy(), self.v.copy(),
                    None if self.adj is None else self.adj.copy(), self.gmtoffset)

    def take(self, idx):
        """Bars at the given index array or slice."""
        return Bars(self.symbol, self.interval, self.t[idx], self.o[idx], self.h[idx],
                    self.l[idx], self.c[idx], self.v[idx],
                    None if self.adj is None else self.adj[idx], self.gmtoffset)

    def tail(self, n):
        return self.take(slice(max(0, len(self) - int(n)), None))

    def adjusted(self):
        """OHLC scaled by adj/close so every price is split and dividend adjusted."""
        if self.adj is None:
            return self.copy()
        with np.errstate(divide="ignore", invalid="ignore"):
            k = np.where(self.c > 0, self.adj / self.c, 1.0)
        k = np.where(np.isfinite(k), k, 1.0)
        return Bars(self.symbol, self.interval, self.t.copy(), self.o * k, self.h * k,
                    self.l * k, self.adj.copy(), self.v.copy(), self.adj.copy(), self.gmtoffset)

    def merge(self, newer):
        """These bars with `newer` laid over them: same timestamps are replaced,
        later ones appended. Used to update a live chart without a full reload."""
        if newer is None or not len(newer):
            return self.copy()
        if not len(self):
            return newer.copy()
        keep = self.t < newer.t[0]
        head = self.take(np.nonzero(keep)[0])
        adj = None
        if self.adj is not None and newer.adj is not None:
            adj = np.concatenate([head.adj, newer.adj])
        return Bars(self.symbol, self.interval,
                    np.concatenate([head.t, newer.t]), np.concatenate([head.o, newer.o]),
                    np.concatenate([head.h, newer.h]), np.concatenate([head.l, newer.l]),
                    np.concatenate([head.c, newer.c]), np.concatenate([head.v, newer.v]),
                    adj, newer.gmtoffset or self.gmtoffset)

    # ------------------------------------------------------------ csv

    def to_csv_text(self):
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["date", "t", "open", "high", "low", "close", "adjclose", "volume"])
        for i in range(len(self)):
            adj = "" if self.adj is None else _fmt(self.adj[i])
            w.writerow([self.date_str(i), int(self.t[i]), _fmt(self.o[i]), _fmt(self.h[i]),
                        _fmt(self.l[i]), _fmt(self.c[i]), adj, "%d" % self.v[i]])
        return out.getvalue()

    def save_csv(self, path):
        data = self.to_csv_text().encode("utf-8")
        if path.endswith(".gz"):
            # no name and mtime=0 keep the file byte-identical when the data has
            # not changed, so a refresh with no new data is not a git change
            with open(path, "wb") as fh:
                with gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as gz:
                    gz.write(data)
        else:
            with open(path, "wb") as fh:
                fh.write(data)

    @classmethod
    def load_csv(cls, path, symbol=None, interval="1d", gmtoffset=0):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            return cls.from_csv_text(fh.read(), symbol, interval, gmtoffset)

    @classmethod
    def from_csv_text(cls, text, symbol=None, interval="1d", gmtoffset=0):
        rows = list(csv.DictReader(io.StringIO(text)))
        t, o, h, l, c, v, adj = [], [], [], [], [], [], []
        has_adj = bool(rows) and all(r.get("adjclose") not in (None, "") for r in rows)
        for r in rows:
            if r.get("t"):
                t.append(int(r["t"]))
            else:
                d = _dt.datetime.strptime(r["date"], "%Y-%m-%d")
                t.append(int((d - _dt.datetime(1970, 1, 1)).total_seconds()) - gmtoffset)
            o.append(float(r["open"]))
            h.append(float(r["high"]))
            l.append(float(r["low"]))
            c.append(float(r["close"]))
            v.append(float(r.get("volume") or 0))
            if has_adj:
                adj.append(float(r["adjclose"]))
        return cls(symbol or "", interval, t, o, h, l, c, v, adj if has_adj else None, gmtoffset)


def _fmt(x):
    return ("%.6f" % x).rstrip("0").rstrip(".") if np.isfinite(x) else ""


def align_daily(bars_by_symbol, start=None, end=None):
    """Put daily bars of several symbols on one calendar.

    Returns (dates, panel) where dates is datetime64[D] and panel maps
    symbol -> dict of arrays (o, h, l, c, v) on those dates. Only dates where
    every symbol has a bar are kept, so nothing is forward-filled or invented.
    """
    if not bars_by_symbol:
        raise ValueError("no symbols")
    common = None
    per = {}
    for sym, b in bars_by_symbol.items():
        d = b.dates()
        # a symbol can carry two bars on one date around data glitches: keep the last
        _, last_idx = np.unique(d[::-1], return_index=True)
        idx = len(d) - 1 - last_idx
        idx.sort()
        per[sym] = (d[idx], b.take(idx))
        common = d[idx] if common is None else np.intersect1d(common, d[idx])
    if start is not None:
        common = common[common >= np.datetime64(start, "D")]
    if end is not None:
        common = common[common <= np.datetime64(end, "D")]
    panel = {}
    for sym, (d, b) in per.items():
        pos = np.searchsorted(d, common)
        panel[sym] = {"o": b.o[pos], "h": b.h[pos], "l": b.l[pos], "c": b.c[pos], "v": b.v[pos]}
    return common, panel
