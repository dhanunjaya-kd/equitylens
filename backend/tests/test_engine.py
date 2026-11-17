"""Offline tests:  python -m pytest tests   (or: python tests/test_engine.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import analysis, parser  # noqa: E402

FX = Path(__file__).parent / "fixtures"


def _load(name):
    return parser.parse_company((FX / name).read_text(encoding="utf-8"), name.split(".")[0].upper())


def test_parse_manufacturer():
    c = _load("testco.html")
    assert c["name"] == "Test Industries Ltd" and c["nse_symbol"] == "TESTCO"
    assert c["ratios"]["current_price"] == 1450 and c["ratios"]["high"] == 1650
    assert len(c["tables"]["profit_loss"]["columns"]) == 13
    assert "Raw PDF" not in c["tables"]["quarters"]["rows"]
    assert c["growth"]["Compounded Profit Growth"]["5 Years"] == 13
    assert not c["is_financial"]


def test_engine_manufacturer():
    a = analysis.analyse(_load("testco.html"), 32.0)
    m = a["metrics"]
    assert m["debt_to_equity"] < 0.1 and m["cfo_to_pat_5"] > 1
    assert a["scores"]["business"] >= 70
    assert a["verdict"]["tone"] == "good"
    assert a["projection"]["available"]
    h = a["projection"]["horizons"]
    for n in ("3", "5", "10"):
        assert h[n]["bear"]["price"] < h[n]["base"]["price"] < h[n]["bull"]["price"]


def test_bank_is_financial():
    a = analysis.analyse(_load("testbank.html"), None)
    assert a["metrics"]["is_financial"]
    assert a["scores"]["cash"] is None
    assert not any("Other income" in f["text"] for f in a["flags"])


def test_peers():
    p = parser.parse_peers((FX / "peers.html").read_text(encoding="utf-8"))
    assert len(p["rows"]) == 3 and p["median"]["P/E"] == 38.5


def test_loss_maker():
    c = _load("testco.html")
    c["tables"]["profit_loss"]["rows"]["EPS in Rs"][-1] = -2.0
    a = analysis.analyse(c, None)
    assert not a["projection"]["available"]
    assert a["verdict"]["tone"] == "bad"


def test_forensics_and_valuation():
    a = analysis.analyse(_load("testco.html"), 31.5)
    fx, v = a["forensics"], a["valuation"]
    assert fx["piotroski"]["available"] and 0 <= fx["piotroski"]["score_9"] <= 9
    assert fx["altman"]["zone"] in ("Safe", "Grey zone", "Distress")
    assert fx["beneish"]["available"] and isinstance(fx["beneish"]["m"], float)
    assert len(fx["dupont"]) >= 5
    assert v["graham_number"] > 0 and v["dcf"]["default_value"] > 0
    assert v["fair_value"]["low"] <= v["fair_value"]["mid"] <= v["fair_value"]["high"]


def test_bank_forensics_skip():
    a = analysis.analyse(_load("testbank.html"), None)
    assert not a["forensics"]["altman"]["available"] and not a["forensics"]["beneish"]["available"]
    assert a["forensics"]["piotroski"]["available"]


def test_documents():
    c = _load("testco.html")
    cats = [d["category"] for d in c["documents"]]
    assert "Annual reports" in cats and "Concalls" in cats


def test_indicators_match_reference():
    from app import technicals as T
    c = [100 + i * 0.5 + (3 if i % 7 == 0 else -2 if i % 5 == 0 else 0) for i in range(300)]
    h = [x + 1.5 for x in c]
    lo = [x - 1.5 for x in c]
    # EMA: seeded with SMA, then the standard recursion
    e = T.ema(c, 20)
    k, ref = 2 / 21, sum(c[:20]) / 20
    for x in c[20:]:
        ref = x * k + ref * (1 - k)
    assert abs(e[-1] - ref) < 1e-9
    r = T.rsi(c)
    assert all(v is None or 0 <= v <= 100 for v in r) and r[-1] is not None
    line, sig, hist = T.macd(c)
    assert abs(hist[-1] - (line[-1] - sig[-1])) < 1e-9
    st, tr, _ = T.supertrend(h, lo, c)
    assert tr[-1] == 1 and st[-1] < c[-1]          # steady uptrend -> buy mode, line below price
    ax, p, m = T.adx(h, lo, c)
    assert ax[-1] > 20 and p[-1] > m[-1]
    w = T.to_weekly([{"t": f"2026-11-{d:02d}", "o": 1, "h": d, "l": 1, "c": d, "v": 1} for d in (9, 10, 11, 12, 13, 16)])
    assert len(w) == 2 and w[0]["h"] == 13 and w[0]["v"] == 5


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)


def test_chart_cache_refreshes_after_each_session_close():
    import datetime as dt
    from app import technicals as T
    ist = T.IST
    ts = lambda *a: dt.datetime(*a, tzinfo=ist).timestamp()
    # cached Friday 13 Nov 16:00 -> Monday 16 Nov 10:00 (market open) -> stale
    assert T.is_stale(ts(2026, 11, 13, 16, 0), ts(2026, 11, 16, 10, 0))
    # cached Monday 09:00, opened Tuesday 06:37 before the open -> Monday's close happened since -> stale
    assert T.is_stale(ts(2026, 11, 16, 9, 0), ts(2026, 11, 17, 6, 37))
    # cached Monday 16:10 (after the close settled), opened Tuesday 06:37 -> still fresh
    assert not T.is_stale(ts(2026, 11, 16, 16, 10), ts(2026, 11, 17, 6, 37))
    # weekend: cached Saturday, opened Sunday -> fresh (no session since)
    assert not T.is_stale(ts(2026, 11, 14, 10, 0), ts(2026, 11, 15, 5, 0))
    # during market hours the forming candle refreshes every few minutes
    assert T.is_stale(ts(2026, 11, 16, 10, 0), ts(2026, 11, 16, 10, 6))
    assert not T.is_stale(ts(2026, 11, 16, 10, 0), ts(2026, 11, 16, 10, 3))


def test_latest_candles_are_merged_into_the_long_history(monkeypatch):
    from app import technicals as T
    long_ = [{"t": "2026-11-12", "o": 1, "h": 1, "l": 1, "c": 100, "v": 1},
             {"t": "2026-11-13", "o": 1, "h": 1, "l": 1, "c": 101, "v": 1}]
    recent = [{"t": "2026-11-13", "o": 1, "h": 1, "l": 1, "c": 101.5, "v": 1}]
    meta = {"regularMarketPrice": 104.0, "regularMarketTime": 1794822000,   # 16 Nov 2026, 15:30 IST
            "regularMarketDayHigh": 105.0, "regularMarketDayLow": 100.5, "regularMarketVolume": 9}

    def fake(sym, rng="10y", with_meta=False):
        return (recent, meta) if with_meta else long_
    monkeypatch.setattr(T, "_yahoo", fake)
    out = T._latest_daily("X.NS")
    assert [b["t"] for b in out] == ["2026-11-12", "2026-11-13", "2026-11-16"]
    assert out[1]["c"] == 101.5 and out[2]["c"] == 104.0 and out[2]["h"] == 105.0


def test_old_or_lagging_chart_cache_is_refetched_and_topped_up(monkeypatch):
    import datetime as dt
    from app import technicals as T
    ts = lambda *a: dt.datetime(*a, tzinfo=T.IST).timestamp()
    assert T.expected_last_session(ts(2026, 11, 17, 6, 47)) == "2026-11-16"
    assert T.expected_last_session(ts(2026, 11, 16, 16, 0)) == "2026-11-16"
    assert T.expected_last_session(ts(2026, 11, 15, 12, 0)) == "2026-11-13"   # Sunday -> Friday
    lagging = [{"t": "2026-11-12", "o": 1, "h": 1, "l": 1, "c": 100, "v": 1},
               {"t": "2026-11-13", "o": 1, "h": 1, "l": 1, "c": 101, "v": 1}] * 1
    lagging = [{"t": f"2026-10-{d:02d}", "o": 1, "h": 1, "l": 1, "c": 90, "v": 1} for d in range(1, 31)] + lagging
    calls = []

    def fake_latest(t):
        calls.append(t)
        if t.endswith(".BO"):
            return lagging + [{"t": "2026-11-16", "o": 1, "h": 1, "l": 1, "c": 103, "v": 1}]
        return list(lagging)
    saved = {}
    monkeypatch.setattr(T.config, "DEMO", False)
    monkeypatch.setattr(T, "_latest_daily", fake_latest)
    monkeypatch.setattr(T.time, "time", lambda: ts(2026, 11, 17, 6, 47))
    monkeypatch.setattr(T.store, "get_company", lambda k: saved.get(k) or ({"KPITTECH": (0, {"company": {"nse_symbol": "KPITTECH", "bse_code": "542651"}})}.get(k)))
    monkeypatch.setattr(T.store, "put_company", lambda k, v: saved.__setitem__(k, (ts(2026, 11, 17, 6, 47), v)))
    # an old-format cache from this morning must be ignored
    saved["CHART::KPITTECH"] = (ts(2026, 11, 17, 6, 30), {"bars": lagging, "source": "x", "ohlc": True})
    bars, src, ohlc = T.get_bars("KPITTECH")
    assert bars[-1]["t"] == "2026-11-16" and bars[-1]["c"] == 103
    assert "542651.BO" in src and calls[0] == "KPITTECH.NS"


def test_stock_page_price_comes_from_the_latest_session(monkeypatch):
    import datetime as dt
    from app import service, technicals as T
    bars = [{"t": "2026-11-13", "o": 1, "h": 1, "l": 1, "c": 550.0, "v": 1},
            {"t": "2026-11-16", "o": 1, "h": 1, "l": 1, "c": 561.0, "v": 1}]
    fetched = dt.datetime(2026, 11, 17, 6, 55, tzinfo=T.IST).timestamp()
    monkeypatch.setattr(T, "get_bars", lambda sym, refresh=False, with_time=False: (bars, "Yahoo Finance (X.NS)", True, fetched))
    company = {"ratios": {"current_price": 550.0, "pe": 50.0, "market_cap": 15000.0, "book_value": 100.0}}
    new, info = service.live_price(company, "X")
    assert new["ratios"]["current_price"] == 561.0
    assert round(new["ratios"]["pe"], 2) == 51.0 and round(new["ratios"]["market_cap"]) == 15300
    assert company["ratios"]["current_price"] == 550.0        # cached fundamentals untouched
    assert info["date"] == "2026-11-16" and info["fetched_at"].startswith("2026-11-17T06:55")


def test_meta_adds_the_session_the_long_series_is_missing():
    from app import technicals as T
    bars = [{"t": "2026-11-13", "o": 1, "h": 2, "l": 1, "c": 101, "v": 1}]
    meta = {"regularMarketPrice": 104.0, "regularMarketTime": 1794822000, "regularMarketDayHigh": 105.0,
            "regularMarketDayLow": 100.5, "regularMarketVolume": 9}
    out = T.apply_meta(bars, meta)
    assert out[-1]["t"] == "2026-11-16" and out[-1]["c"] == 104.0 and len(bars) == 1
    assert T.apply_meta(out, meta) == out        # already there: nothing added
