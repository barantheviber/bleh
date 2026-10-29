from research.fetch_data import read_tickers


def test_read_tickers_skips_comments_and_duplicates(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("# header\nspy QQQ  # inline\n\nSPY iwm\n", encoding="utf-8")
    assert read_tickers(str(p)) == ["SPY", "QQQ", "IWM"]


def _bars_on(day):
    import datetime as dt

    import numpy as np

    from traderbot.data.bars import Bars
    days = [dt.date(2026, 10, 27), dt.date(2026, 10, 28), day]
    t = [int((dt.datetime.combine(d, dt.time(13, 30)) - dt.datetime(1970, 1, 1)).total_seconds())
         for d in days]
    ones = np.ones(3)
    return Bars("SPY", "1d", t, ones, ones, ones, ones, ones, ones, gmtoffset=-14400)


def test_an_unfinished_session_bar_is_dropped():
    import datetime as dt

    from research.fetch_data import drop_unfinished
    today = dt.date(2026, 10, 29)
    during = drop_unfinished(_bars_on(today), dt.datetime(2026, 10, 29, 18, 0))   # 14:00 EDT
    assert during.date_str(-1) == "2026-10-28" and len(during) == 2
    settling = drop_unfinished(_bars_on(today), dt.datetime(2026, 10, 29, 20, 10))
    assert len(settling) == 2                       # 16:10, closing prints may still move
    after = drop_unfinished(_bars_on(today), dt.datetime(2026, 10, 29, 20, 31))
    assert after.date_str(-1) == "2026-10-29"
    older = drop_unfinished(_bars_on(dt.date(2026, 10, 29)), dt.datetime(2026, 10, 30, 15, 0))
    assert len(older) == 3                          # yesterday's bar is final
