import io
import json
import urllib.error

import pytest

from traderbot.data.yahoo import (DataError, YahooClient, parse_chart, quote_from_meta,
                                  range_start)

# Shape of a real v8 chart response for SPY, interval=1d, range=5d (values trimmed).
# The third day has a null row, which Yahoo sends around halts and data gaps.
CHART = {
    "chart": {
        "result": [{
            "meta": {
                "currency": "USD", "symbol": "SPY", "exchangeName": "PCX",
                "fullExchangeName": "NYSEArca", "instrumentType": "ETF",
                "regularMarketTime": 1761681600, "gmtoffset": -14400,
                "timezone": "EDT", "exchangeTimezoneName": "America/New_York",
                "regularMarketPrice": 687.06, "chartPreviousClose": 671.29,
                "longName": "SPDR S&P 500 ETF Trust", "shortName": "SPDR S&P 500",
                "dataGranularity": "1d", "range": "5d",
            },
            # 2025-10-22 .. 2025-10-28 09:30 New York (EDT)
            "timestamp": [1761139800, 1761226200, 1761312600, 1761571800, 1761658200],
            "indicators": {
                "quote": [{
                    "open": [672.0, 668.1, None, 680.0, 684.9],
                    "high": [674.1, 671.0, None, 685.5, 688.4],
                    "low": [665.2, 666.3, None, 679.1, 683.0],
                    "close": [667.8, 670.2, None, 685.2, 687.06],
                    "volume": [81000000, 64000000, None, 59000000, 44000000],
                }],
                "adjclose": [{"adjclose": [667.8, 670.2, None, 685.2, 687.06]}],
            },
        }],
        "error": None,
    }
}


class FakeNet(object):
    """Replays responses in order: bytes, or an exception to raise."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, req, timeout):
        self.urls.append(req.full_url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def http_error(code, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(data))


def test_parse_chart_drops_null_rows_and_keeps_adj():
    bars, meta = parse_chart(CHART, "SPY", "1d")
    assert len(bars) == 4
    assert list(bars.c) == [667.8, 670.2, 685.2, 687.06]
    assert list(bars.adj) == [667.8, 670.2, 685.2, 687.06]
    assert bars.gmtoffset == -14400
    assert bars.date_str(0) == "2025-10-22" and bars.date_str(-1) == "2025-10-28"
    assert meta["exchangeTimezoneName"] == "America/New_York"


def test_parse_chart_error_payload_raises():
    with pytest.raises(DataError) as e:
        parse_chart({"chart": {"result": None, "error": {
            "code": "Not Found", "description": "No data found, symbol may be delisted"}}},
            "ZZZZ", "1d")
    assert "delisted" in str(e.value)


def test_parse_chart_intraday_without_adjclose():
    data = json.loads(json.dumps(CHART))
    del data["chart"]["result"][0]["indicators"]["adjclose"]
    bars, _ = parse_chart(data, "SPY", "5m")
    assert bars.adj is None and len(bars) == 4


def test_quote_uses_last_close_before_the_trade_date():
    bars, meta = parse_chart(CHART, "SPY", "1d")
    q = quote_from_meta("SPY", meta, bars)
    # regularMarketTime is 2025-10-28, so the previous close is 2025-10-27's 685.2,
    # not chartPreviousClose (671.29), which is the close before the 5-day window
    assert q.prev_close == 685.2
    assert q.price == 687.06
    assert round(q.change, 2) == 1.86
    assert round(q.change_pct, 3) == 0.271
    assert q.name == "SPDR S&P 500 ETF Trust"


def test_client_daily_uses_explicit_dates_not_range():
    net = FakeNet(json.dumps(CHART).encode())
    bars, _ = YahooClient(opener=net, sleep=lambda s: None).chart("spy", "1d", range_="5d")
    assert len(bars) == 4
    url = net.urls[0]
    assert url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/SPY?")
    assert "interval=1d" in url and "period1=" in url and "period2=" in url
    assert "range=" not in url


def test_client_max_daily_starts_in_1900():
    net = FakeNet(json.dumps(CHART).encode())
    YahooClient(opener=net).chart("SPY", "1d", range_="max")
    assert "period1=-2208994789" in net.urls[0]


def test_client_intraday_uses_range():
    data = json.loads(json.dumps(CHART))
    data["chart"]["result"][0]["meta"]["dataGranularity"] = "5m"
    net = FakeNet(json.dumps(data).encode())
    YahooClient(opener=net).chart("SPY", "5m", range_="1d")
    assert "range=1d" in net.urls[0] and "period1" not in net.urls[0]


def test_client_rejects_downgraded_granularity():
    data = json.loads(json.dumps(CHART))
    data["chart"]["result"][0]["meta"]["dataGranularity"] = "1mo"
    with pytest.raises(DataError) as e:
        YahooClient(opener=FakeNet(json.dumps(data).encode())).chart("SPY", "1d", range_="max")
    assert "1mo" in str(e.value)


def test_range_start():
    end = 1761681600  # 2025-10-28 20:00 UTC
    assert range_start("5d", end) == end - 5 * 86400
    assert range_start("2y", end) == end - 2 * 366 * 86400
    assert range_start("6mo", end) == end - 6 * 31 * 86400
    assert range_start("ytd", end) == 1735689600  # 2025-01-01 00:00 UTC
    assert range_start("max", end) == -2208994789
    with pytest.raises(DataError):
        range_start("forever", end)


def test_client_retries_on_second_host_after_network_error():
    net = FakeNet(urllib.error.URLError("reset"), json.dumps(CHART).encode())
    slept = []
    bars, _ = YahooClient(opener=net, sleep=slept.append).chart("SPY")
    assert len(bars) == 4
    assert "query2.finance.yahoo.com" in net.urls[1]
    assert slept == [1.5]


def test_client_404_raises_without_retry():
    net = FakeNet(http_error(404, {"chart": {"result": None, "error": {
        "code": "Not Found", "description": "No data found, symbol may be delisted"}}}))
    with pytest.raises(DataError) as e:
        YahooClient(opener=net, sleep=lambda s: None).chart("ZZZZ")
    assert "delisted" in str(e.value)
    assert len(net.urls) == 1


def test_client_gives_up_after_retries():
    net = FakeNet(http_error(429), http_error(429), http_error(503))
    with pytest.raises(DataError) as e:
        YahooClient(opener=net, retries=2, sleep=lambda s: None).chart("SPY")
    assert "503" in str(e.value)
    assert len(net.urls) == 3


def test_client_rejects_unknown_interval():
    with pytest.raises(DataError):
        YahooClient(opener=FakeNet()).chart("SPY", "7m")


def test_search_parses_quotes():
    body = {"quotes": [
        {"symbol": "AAPL", "longname": "Apple Inc.", "exchDisp": "NASDAQ", "typeDisp": "Equity"},
        {"symbol": "THYAO.IS", "shortname": "TURK HAVA YOLLARI", "exchDisp": "Istanbul",
         "typeDisp": "Equity"},
        {"longname": "no symbol, skipped"},
    ]}
    res = YahooClient(opener=FakeNet(json.dumps(body).encode())).search("apple")
    assert [r["symbol"] for r in res] == ["AAPL", "THYAO.IS"]
    assert res[1]["name"] == "TURK HAVA YOLLARI"
