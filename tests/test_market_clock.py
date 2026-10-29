import datetime as dt

import pytest

from traderbot import market_clock as mc

D = dt.date

# NYSE's published lists: 2026 and 2027 as written in trader-skill's
# trader-alerts/SKILL.md (read from nyse.com on 2026-10-13); 2024 and 2025
# from NYSE's past calendars.
PUBLISHED = {
    2024: ([D(2024, 1, 1), D(2024, 1, 15), D(2024, 2, 19), D(2024, 3, 29), D(2024, 5, 27),
            D(2024, 6, 19), D(2024, 7, 4), D(2024, 9, 2), D(2024, 11, 28), D(2024, 12, 25)],
           [D(2024, 7, 3), D(2024, 11, 29), D(2024, 12, 24)]),
    2025: ([D(2025, 1, 1), D(2025, 1, 9), D(2025, 1, 20), D(2025, 2, 17), D(2025, 4, 18),
            D(2025, 5, 26), D(2025, 6, 19), D(2025, 7, 4), D(2025, 9, 1), D(2025, 11, 27),
            D(2025, 12, 25)],
           [D(2025, 7, 3), D(2025, 11, 28), D(2025, 12, 24)]),
    2026: ([D(2026, 1, 1), D(2026, 1, 19), D(2026, 2, 16), D(2026, 4, 3), D(2026, 5, 25),
            D(2026, 6, 19), D(2026, 7, 3), D(2026, 9, 7), D(2026, 11, 26), D(2026, 12, 25)],
           [D(2026, 11, 27), D(2026, 12, 24)]),
    2027: ([D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26), D(2027, 5, 31),
            D(2027, 6, 18), D(2027, 7, 5), D(2027, 9, 6), D(2027, 11, 25), D(2027, 12, 24)],
           [D(2027, 11, 26)]),
}


@pytest.mark.parametrize("year", sorted(PUBLISHED))
def test_holidays_match_published_calendar(year):
    hol, early = PUBLISHED[year]
    assert sorted(mc.holidays(year)) == hol
    assert sorted(mc.early_closes(year)) == early


def test_saturday_new_year_is_not_moved_to_friday():
    # 2028-01-01 is a Saturday: NYSE stays open on Friday 2027-12-31
    assert D(2027, 12, 31) not in mc.holidays(2027)
    assert mc.is_trading_day(D(2027, 12, 31))


def test_easter():
    assert mc.easter(2024) == D(2024, 3, 31)
    assert mc.easter(2025) == D(2025, 4, 20)
    assert mc.easter(2026) == D(2026, 4, 5)
    assert mc.easter(2027) == D(2027, 3, 28)


def test_dst_boundaries():
    # 2026: DST from 2026-03-08 07:00 UTC to 2026-11-01 06:00 UTC
    assert mc.ny_offset(dt.datetime(2026, 3, 8, 6, 59)) == dt.timedelta(hours=-5)
    assert mc.ny_offset(dt.datetime(2026, 3, 8, 7, 0)) == dt.timedelta(hours=-4)
    assert mc.ny_offset(dt.datetime(2026, 11, 1, 5, 59)) == dt.timedelta(hours=-4)
    assert mc.ny_offset(dt.datetime(2026, 11, 1, 6, 0)) == dt.timedelta(hours=-5)


def test_ny_to_utc_round_trip():
    for local in (dt.datetime(2026, 1, 15, 9, 30), dt.datetime(2026, 7, 15, 16, 0),
                  dt.datetime(2026, 11, 27, 13, 0)):
        assert mc.to_ny(mc.ny_to_utc(local)) == local


def test_status_open_pre_post_weekend_holiday():
    # Wednesday 2026-10-28, 14:30 UTC = 10:30 EDT
    s = mc.status(dt.datetime(2026, 10, 28, 14, 30))
    assert s["open"] and s["state"] == "open" and s["next_close"].hour == 16
    s = mc.status(dt.datetime(2026, 10, 28, 12, 0))   # 08:00 EDT
    assert not s["open"] and s["state"] == "pre" and s["next_open"] == dt.datetime(2026, 10, 28, 9, 30)
    s = mc.status(dt.datetime(2026, 10, 28, 21, 0))   # 17:00 EDT
    assert s["state"] == "post" and s["next_open"] == dt.datetime(2026, 10, 29, 9, 30)
    s = mc.status(dt.datetime(2026, 10, 31, 15, 0))   # Saturday
    assert s["state"] == "closed" and s["reason"] == "Hafta sonu"
    assert s["next_open"] == dt.datetime(2026, 11, 2, 9, 30)
    s = mc.status(dt.datetime(2026, 11, 26, 15, 0))   # Thanksgiving
    assert s["reason"].startswith("Tatil") and s["next_open"].date() == D(2026, 11, 27)


def test_early_close_session_and_status():
    assert mc.session(D(2026, 11, 27))[1] == dt.datetime(2026, 11, 27, 13, 0)
    s = mc.status(dt.datetime(2026, 11, 27, 18, 30))  # 13:30 EST, after the early close
    assert not s["open"] and s["state"] == "post"


def test_next_and_prev_trading_day():
    assert mc.next_trading_day(D(2026, 11, 25)) == D(2026, 11, 27)
    assert mc.prev_trading_day(D(2026, 11, 30)) == D(2026, 11, 27)
    assert mc.next_trading_day(D(2026, 12, 31)) == D(2027, 1, 4)


def test_describe_is_turkish():
    txt = mc.describe(mc.status(dt.datetime(2026, 10, 28, 14, 30)))
    assert txt.startswith("NYSE AÇIK")
