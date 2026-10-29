import numpy as np

from traderbot.data.bars import Bars, align_daily

# 2024-01-02 .. 2024-01-05, 09:30 New York (EST, UTC-5)
T = np.array([1704205800, 1704292200, 1704378600, 1704465000])
EST = -18000


def make(sym="SPY", t=T, c=(10.5, 11.5, 12.5, 13.5), adj=(10, 11, 12, 13)):
    n = len(t)
    o = [10, 11, 12, 13][:n]
    return Bars(sym, "1d", t, o, [x + 1 for x in o], [x - 1 for x in o], list(c)[:n],
                [100] * n, None if adj is None else list(adj)[:n], EST)


def test_dates_use_exchange_offset():
    b = make()
    assert [b.date_str(i) for i in range(4)] == ["2024-01-02", "2024-01-03",
                                                 "2024-01-04", "2024-01-05"]
    assert str(b.dates()[0]) == "2024-01-02"


def test_adjusted_scales_ohlc_by_adj_over_close():
    a = make().adjusted()
    assert np.allclose(a.c, [10, 11, 12, 13])
    assert np.isclose(a.o[0], 10 * 10 / 10.5)
    assert np.isclose(a.h[0], 11 * 10 / 10.5)


def test_adjusted_without_adj_is_a_copy():
    b = make(adj=None)
    a = b.adjusted()
    assert np.allclose(a.c, b.c) and a is not b


def test_merge_replaces_overlap_and_appends():
    b = make()
    newer = Bars("SPY", "1d", [T[-1], T[-1] + 86400], [1, 2], [1, 2], [1, 2], [7, 8], [1, 1],
                 [7, 8], EST)
    m = b.merge(newer)
    assert len(m) == 5
    assert list(m.c) == [10.5, 11.5, 12.5, 7, 8]


def test_merge_with_empty_returns_copy():
    b = make()
    empty = Bars("SPY", "1d", [], [], [], [], [], [], None, EST)
    assert len(b.merge(empty)) == 4
    assert len(empty.merge(b)) == 4


def test_csv_round_trip_gz(tmp_path):
    b = make()
    p = str(tmp_path / "spy.csv.gz")
    b.save_csv(p)
    r = Bars.load_csv(p, "SPY", gmtoffset=EST)
    assert (r.t == b.t).all()
    assert np.allclose(r.c, b.c) and np.allclose(r.adj, b.adj) and np.allclose(r.v, b.v)


def test_csv_save_is_deterministic(tmp_path):
    b = make()
    p1, p2 = str(tmp_path / "a.csv.gz"), str(tmp_path / "b.csv.gz")
    b.save_csv(p1)
    b.save_csv(p2)
    assert open(p1, "rb").read() == open(p2, "rb").read()


def test_align_daily_keeps_only_common_dates():
    spy = make()
    qqq = make("QQQ", t=T[1:], c=(5, 6, 7), adj=None)
    dates, panel = align_daily({"SPY": spy, "QQQ": qqq})
    assert [str(d) for d in dates] == ["2024-01-03", "2024-01-04", "2024-01-05"]
    assert list(panel["SPY"]["c"]) == [11.5, 12.5, 13.5]
    assert list(panel["QQQ"]["c"]) == [5, 6, 7]


def test_align_daily_start_end_filter():
    dates, panel = align_daily({"SPY": make()}, start="2024-01-03", end="2024-01-04")
    assert [str(d) for d in dates] == ["2024-01-03", "2024-01-04"]
    assert list(panel["SPY"]["c"]) == [11.5, 12.5]


def test_length_mismatch_raises():
    try:
        Bars("X", "1d", [1, 2], [1], [1, 2], [1, 2], [1, 2], [1, 2])
    except ValueError:
        return
    raise AssertionError("expected ValueError")
