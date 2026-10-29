"""Market calendar for the coming weeks: Fed decisions, NYSE holidays and
early closes, and the turn-of-the-month window."""

import datetime as dt

from . import market_clock

# The Fed's published schedule: the second day of each FOMC meeting, when the
# statement comes out at 14:00 New York time. True = with the Summary of
# Economic Projections (the "dot plot"). The 2027 dates are tentative until
# confirmed at the meeting before each one; update this list every year.
FOMC = {
    dt.date(2026, 1, 28): False, dt.date(2026, 3, 18): True, dt.date(2026, 4, 29): False,
    dt.date(2026, 6, 17): True, dt.date(2026, 7, 29): False, dt.date(2026, 9, 16): True,
    dt.date(2026, 10, 28): False, dt.date(2026, 12, 9): True,
    dt.date(2027, 1, 27): False, dt.date(2027, 3, 17): True, dt.date(2027, 4, 28): False,
    dt.date(2027, 6, 9): True, dt.date(2027, 7, 28): False, dt.date(2027, 9, 15): True,
    dt.date(2027, 10, 27): False, dt.date(2027, 12, 8): True,
}
TENTATIVE_FROM = dt.date(2027, 1, 1)

FOMC_NOTE = ("Lucca ve Moench (2015): 1994-2011'de hisseler karardan önceki 24 saatte "
             "ortalamanın çok üstünde getiri sağladı; 2018 güncellemesine göre etki sürüyor ama "
             "bir gün önceden başlıyor.")
TOM_NOTE = ("McConnell ve Xu (2008): 1926-2005'te ABD hisse getirisinin büyük kısmı ayın son "
            "ve sonraki ayın ilk 3 işlem gününde geldi; daha yeni çalışmalar etkinin zayıfladığını "
            "söylüyor. Botun Ay Dönümü stratejisi bunu dener.")


def _sessions(first, last):
    d, out = first, []
    while d <= last:
        if market_clock.is_trading_day(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def upcoming(today, days=45):
    """Events from `today` through `today + days`, oldest first:
    [{"date", "kind": fomc|holiday|early|tom, "title", "note"}]."""
    last = today + dt.timedelta(days=days)
    out = []
    for d, sep in sorted(FOMC.items()):
        if today <= d <= last:
            title = "FOMC faiz kararı, 14:00 New York"
            if sep:
                title += " (ekonomik projeksiyonlarla)"
            if d >= TENTATIVE_FROM:
                title += " · geçici tarih"
            out.append({"date": d, "kind": "fomc", "title": title, "note": FOMC_NOTE})
    for y in range(today.year, last.year + 1):
        for d, name in market_clock.holidays(y).items():
            if today <= d <= last and d.weekday() < 5:
                out.append({"date": d, "kind": "holiday", "title": "NYSE kapalı: %s" % name,
                            "note": "Bot o gün işlem yapmaz."})
        for d in market_clock.early_closes(y):
            if today <= d <= last:
                out.append({"date": d, "kind": "early", "title": "NYSE erken kapanış (13:00)",
                            "note": "Seans 13:00'te biter; bot karar saatini buna göre "
                                    "geçmemelidir."})
    # the turn-of-the-month window: the last session of a month and the first
    # three of the next, listed on its first day
    sessions = _sessions(today - dt.timedelta(days=7), last + dt.timedelta(days=10))
    for a, b in zip(sessions, sessions[1:]):
        if a.month != b.month and today <= a <= last:
            nxt = [s for s in sessions if (s.year, s.month) == (b.year, b.month)][:3]
            out.append({"date": a, "kind": "tom",
                        "title": "Ay dönümü penceresi: %s - %s" % (
                            a.strftime("%d.%m"), nxt[-1].strftime("%d.%m")),
                        "note": TOM_NOTE})
    order = {"holiday": 0, "early": 1, "fomc": 2, "tom": 3}
    return sorted(out, key=lambda e: (e["date"], order[e["kind"]]))
