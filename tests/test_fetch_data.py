from research.fetch_data import read_tickers


def test_read_tickers_skips_comments_and_duplicates(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("# header\nspy QQQ  # inline\n\nSPY iwm\n", encoding="utf-8")
    assert read_tickers(str(p)) == ["SPY", "QQQ", "IWM"]
