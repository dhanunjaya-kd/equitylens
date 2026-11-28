"""Tests for vault encryption, WAL/indexed rankings, SSE AI streaming, price alerts, and Today/Terminal upgrades."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ["EQL_DATA_DIR"] = tempfile.mkdtemp()
os.environ.pop("EQL_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, alerts, brokers, store, terminal, vault  # noqa: E402
from app.main import app  # noqa: E402

store.init()


def test_vault_roundtrip_and_tamper():
    enc = vault.encrypt("sk-ant-secret-12345")
    assert enc.startswith(vault.PREFIX) and "secret" not in enc
    assert vault.decrypt(enc) == "sk-ant-secret-12345"
    assert vault.decrypt("legacy-plaintext") == "legacy-plaintext"
    bad = enc[:-4] + ("AAAA" if enc[-4:] != "AAAA" else "BBBB")
    assert vault.decrypt(bad) == ""


def test_secrets_encrypted_on_disk():
    ai.save_settings({"provider": "claude", "anthropic_api_key": "sk-ant-disk-secret-99"})
    raw_ai = ai.SETTINGS_FILE.read_text(encoding="utf-8")
    assert "sk-ant-disk-secret-99" not in raw_ai and vault.PREFIX in raw_ai
    assert ai.load_settings()["anthropic_api_key"] == "sk-ant-disk-secret-99"
    ai.save_settings({"provider": "demo"})

    brokers.configure("zerodha", {"api_key": "k1", "api_secret": "brk-secret-88"})
    raw_brk = brokers.FILE.read_text(encoding="utf-8")
    assert "brk-secret-88" not in raw_brk and vault.PREFIX in raw_brk
    assert brokers._cfg("zerodha")["api_secret"] == "brk-secret-88"
    brokers.forget("zerodha")

    alerts.save({"token": "12345:AA-tg-secret"})
    hit = store.get_company(alerts.KEY)[1]
    assert vault.is_encrypted(hit["token"]) and alerts.settings()["token"] == "12345:AA-tg-secret"


def test_store_wal_and_ranking_cache():
    mode = store._conn().execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() in ("wal", "delete", "memory")
    store.put_ranking("TESTCO", {"symbol": "TESTCO", "market": "IN", "overall": 82, "market_cap": 5000, "verdict": "High quality, fairly priced"})
    rows = store.all_rankings()
    assert any(r["symbol"] == "TESTCO" and r["overall"] == 82 for r in rows)


def test_terminal_straddle_and_expected_move():
    js = {"records": {"expiryDates": ["03-Dec-2026"], "underlyingValue": 25600.0, "timestamp": "28-Nov-2026 12:00:00",
                      "data": [{"strikePrice": 25600, "expiryDate": "03-Dec-2026",
                                "CE": {"openInterest": 1000, "lastPrice": 180.0},
                                "PE": {"openInterest": 1200, "lastPrice": 162.0}}]}}
    c = terminal.parse_chain(js)
    assert c["straddle"] == 342.0
    assert c["expected_move_pct"] == round(342.0 / 25600.0 * 100, 2)


def test_price_alerts_and_streaming_endpoints():
    c = TestClient(app)
    r = c.post("/api/alerts/price", json={"sym": "TCS", "dir": "above", "price": 4000, "telegram": True})
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    aid = r.json()["items"][0]["id"]
    assert alerts.check_price_alerts({"TCS": 4050.0}) == 0
    items = alerts.price_alerts_list()
    assert items[0]["hit"] is not None
    assert c.delete(f"/api/alerts/price/{aid}").json()["items"] == []

    sec = c.get("/api/security/status")
    assert sec.status_code == 200 and sec.json()["vault_encrypted"] is True

    s_note = c.post("/api/ai/stream/note/TESTCO")
    assert s_note.status_code == 200 and '"type": "done"' in s_note.text

    s_chat = c.post("/api/ai/stream/chat/TESTCO", json={"messages": [{"role": "user", "content": "ROCE?"}]})
    assert s_chat.status_code == 200 and '"type": "done"' in s_chat.text

    tod = c.get("/api/today?market=IN").json()
    assert "sectors" in tod and "flips" in tod


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
