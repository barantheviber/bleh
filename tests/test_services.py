"""The 13F, news and Congress services on trader-skill's own recorded
fixtures (tests/fixtures/skills, MIT, copied from the trader-skill repo)."""

import datetime as dt
import os

import pytest

from traderbot import services

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "skills")
BRK = "1067983"


def test_sec_user_agent_rules():
    assert services.sec_user_agent(" Ada Lovelace ada@example.org ") == "Ada Lovelace ada@example.org"
    for bad in ("", "no email", "Your Name you@example.com"):
        with pytest.raises(services.ServiceError):
            services.sec_user_agent(bad)


def test_find_filers_bundled_and_sec_search():
    hits = services.find_filers("buffett")
    assert hits[0]["cik"] == "0001067983" and hits[0]["source"] == "bundled"
    sec = services.find_filers("scion asset", offline=os.path.join(FIX, "copycat"))
    assert any(h["source"] == "sec" for h in sec) or any("Scion" in h["name"] for h in sec)


def test_holdings_and_copy_targets_match_the_skill_reel():
    res = services.holdings(BRK, None, offline=os.path.join(FIX, "copycat"))
    top = [(p["ticker"], round(p["pct_of_13f"], 2)) for p in res["positions"][:5]]
    assert top == [("AAPL", 22.04), ("AXP", 17.14), ("GOOGL", 12.62), ("KO", 10.86),
                   ("BAC", 9.2)]
    assert res["meta"]["period"] == "2026-06-30" and res["meta"]["filed"] == "2026-08-14"
    t = services.copy_targets(res, top=5)
    assert [w["weight"] for w in t["weights"]] == [30.67, 23.85, 17.56, 15.11, 12.8]
    assert t["as_of"] == "2026-06-30" and t["caveats"]


def test_quarter_diff_finds_new_and_sold():
    d = services.quarter_diff(BRK, None, offline=os.path.join(FIX, "copycat"))
    status = {c.get("ticker"): c["status"] for c in d["changes"]}
    assert status.get("DHI") == "NEW"
    assert any(c["status"] == "SOLD OUT" for c in d["changes"])
    assert d["meta"]["prior_period"] == "2026-03-31"


def test_headlines_offline(tmp_path):
    items, notes = services.headlines(["AAPL", "KO"], ua=None, hours=24 * 400,
                                      state_path=str(tmp_path / "news.json"),
                                      offline=os.path.join(FIX, "news"),
                                      now=dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc))
    assert items, notes
    assert all(i["touches"] for i in items)
    times = [i["time"] for i in items if i["time"]]
    assert times == sorted(times, reverse=True)
    assert any(i["kind"] == "filing" for i in items)


def test_congress_filings_offline():
    rows = services.congress_filings(2026, ["pelosi"], offline=os.path.join(FIX, "pelosi",
                                                                            "2026FD.zip"))
    assert [r["doc_id"] for r in rows] == ["20035553", "20035143", "20034836", "20033725"]
    assert rows[1]["url"].endswith("/2026/20035143.pdf")


def test_read_ptr_rejects_odd_ids(tmp_path):
    with pytest.raises(services.ServiceError):
        services.read_ptr("../../etc/passwd", 2026, pdf_dir=str(tmp_path))
