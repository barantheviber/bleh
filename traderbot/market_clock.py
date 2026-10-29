"""NYSE trading calendar and New York time, with no time zone files.

Regular session 09:30-16:00 New York time; 13:00 close on early-close days.
Holidays follow NYSE's rules (weekend observance included); the published
2026 and 2027 lists in trader-skill's alerts.py are checked in the tests.
US daylight saving time (second Sunday of March to first Sunday of November)
is computed here, so the Windows build needs no tzdata.

Unscheduled closures (a national day of mourning) cannot be predicted; the
known ones are listed in SPECIAL_CLOSURES, and with Alpaca connected the
broker's own clock is used instead.
"""

import datetime as dt

OPEN = dt.time(9, 30)
CLOSE = dt.time(16, 0)
EARLY_CLOSE = dt.time(13, 0)
SPECIAL_CLOSURES = {dt.date(2025, 1, 9): "Ulusal yas günü (Jimmy Carter)"}


# ---------------------------------------------------------------- time

def _nth_weekday(year, month, weekday, n):
    """n-th (1-based) weekday of a month; n=-1 for the last one. Monday=0."""
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def ny_offset(utc):
    """New York's UTC offset at a UTC instant (naive or aware)."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(dt.timezone.utc).replace(tzinfo=None)
    y = utc.year
    start = dt.datetime.combine(_nth_weekday(y, 3, 6, 2), dt.time(7, 0))   # 2:00 EST
    end = dt.datetime.combine(_nth_weekday(y, 11, 6, 1), dt.time(6, 0))    # 2:00 EDT
    return dt.timedelta(hours=-4) if start <= utc < end else dt.timedelta(hours=-5)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def to_ny(utc):
    """Naive New York local time for a UTC instant."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return utc + ny_offset(utc)


def ny_to_utc(local):
    """UTC for a naive New York local time. Only the 01:00-03:00 hours of the
    two switch nights are ambiguous, and no session touches them."""
    summer = local + dt.timedelta(hours=4)
    if ny_offset(summer) == dt.timedelta(hours=-4):
        return summer
    return local + dt.timedelta(hours=5)


def ny_now():
    return to_ny(utc_now())


# ---------------------------------------------------------------- calendar

def easter(year):
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _observed(d):
    """Saturday holidays move to Friday, Sunday ones to Monday."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def holidays(year):
    """{date: name} of full-day NYSE closures in a year."""
    out = {}
    ny = dt.date(year, 1, 1)
    if ny.weekday() != 5:  # NYSE does not close the Friday before a Saturday New Year
        out[_observed(ny)] = "Yılbaşı"
    out[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Günü"
    out[_nth_weekday(year, 2, 0, 3)] = "Başkanlar Günü"
    out[easter(year) - dt.timedelta(days=2)] = "Kutsal Cuma"
    out[_nth_weekday(year, 5, 0, -1)] = "Anma Günü"
    if year >= 2022:
        out[_observed(dt.date(year, 6, 19))] = "Juneteenth"
    out[_observed(dt.date(year, 7, 4))] = "Bağımsızlık Günü"
    out[_nth_weekday(year, 9, 0, 1)] = "İşçi Bayramı"
    out[_nth_weekday(year, 11, 3, 4)] = "Şükran Günü"
    out[_observed(dt.date(year, 12, 25))] = "Noel"
    for d, name in SPECIAL_CLOSURES.items():
        if d.year == year:
            out[d] = name
    return out


def early_closes(year):
    """Days the market closes at 13:00: July 3 when July 4 is Tue-Fri, the day
    after Thanksgiving, and Christmas Eve when it is a regular weekday."""
    hol = holidays(year)
    out = set()
    jul3 = dt.date(year, 7, 3)
    if jul3.weekday() < 4 and jul3 not in hol:
        out.add(jul3)
    out.add(_nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1))
    xmas_eve = dt.date(year, 12, 24)
    if xmas_eve.weekday() < 5 and xmas_eve not in hol:
        out.add(xmas_eve)
    return out


def is_trading_day(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def session(d):
    """(open, close) as naive New York datetimes, or None on a closed day."""
    if not is_trading_day(d):
        return None
    close = EARLY_CLOSE if d in early_closes(d.year) else CLOSE
    return dt.datetime.combine(d, OPEN), dt.datetime.combine(d, close)


def next_trading_day(d):
    """The first trading day strictly after d."""
    d = d + dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def prev_trading_day(d):
    d = d - dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def status(utc=None):
    """Market state at a UTC instant (default now):
    {"open": bool, "state": "open"|"pre"|"post"|"closed", "ny": datetime,
     "session": (open, close) or None, "next_open": datetime, "next_close": datetime|None,
     "reason": str}"""
    utc = utc or utc_now()
    now = to_ny(utc)
    today = now.date()
    sess = session(today)
    out = {"ny": now, "session": sess, "open": False, "next_close": None, "reason": ""}
    if sess and sess[0] <= now < sess[1]:
        out.update(open=True, state="open", next_close=sess[1])
        nxt = session(next_trading_day(today))
        out["next_open"] = nxt[0]
        out["reason"] = "Piyasa açık, %s'de kapanıyor" % sess[1].strftime("%H:%M")
        return out
    if sess and now < sess[0]:
        out.update(state="pre", next_open=sess[0], next_close=sess[1])
        out["reason"] = "Açılış öncesi, %s'de açılıyor" % sess[0].strftime("%H:%M")
        return out
    nxt_day = next_trading_day(today)
    nxt = session(nxt_day)
    out.update(state="post" if sess else "closed", next_open=nxt[0], next_close=nxt[1])
    if sess:
        out["reason"] = "Seans bitti"
    elif today.weekday() >= 5:
        out["reason"] = "Hafta sonu"
    else:
        out["reason"] = "Tatil: %s" % holidays(today.year).get(today, "kapalı")
    return out


def describe(st):
    """One line for the status bar, e.g. 'NYSE AÇIK · NY 10:42 · kapanış 16:00'."""
    ny = st["ny"].strftime("%H:%M")
    if st["open"]:
        return "NYSE AÇIK · NY %s · kapanış %s" % (ny, st["next_close"].strftime("%H:%M"))
    nxt = st["next_open"]
    when = nxt.strftime("%d.%m %H:%M")
    return "NYSE KAPALI (%s) · NY %s · açılış %s" % (st["reason"], ny, when)
