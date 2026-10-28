import json
import sys

from traderbot import config, keystore


def test_keystore_round_trip_and_mask():
    secret = "PKABCDEFGH12345678"
    enc = keystore.protect(secret)
    assert enc.startswith("dpapi:" if sys.platform.startswith("win") else "plain:")
    assert secret not in enc
    assert keystore.unprotect(enc) == secret
    assert keystore.unprotect("") == "" and keystore.unprotect("junk") == ""
    assert keystore.mask(secret) == "PKAB…5678"


def test_settings_defaults_merge_and_secrets(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"risk": {"max_daily_loss_pct": 3}, "broker": "sim"}),
                    encoding="utf-8")
    s = config.Settings(str(path))
    risk = s.get("risk")
    assert risk["max_daily_loss_pct"] == 3 and risk["cash_buffer_pct"] == 2  # merged
    assert s.get("strategy")["key"] == "vol_target"
    s.set_secret("alpaca_secret", " SECRET123 ")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "SECRET123" not in json.dumps(raw)
    assert config.Settings(str(path)).secret("alpaca_secret") == "SECRET123"


def test_broken_settings_file_is_kept_aside(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    s = config.Settings(str(path))
    assert s.get("broker") == "sim"
    assert (tmp_path / "s.json.broken").exists()


def test_live_requires_alpaca_and_live_flag(tmp_path):
    s = config.Settings(str(tmp_path / "s.json"))
    assert not s.is_live()
    s.update({"broker": "alpaca", "alpaca_paper": False})
    assert s.is_live()
