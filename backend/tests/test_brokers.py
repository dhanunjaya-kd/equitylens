"""Broker holdings formats, TOTP, holdings-file import and the portfolio X-ray (offline):  python tests/test_brokers.py"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import brokers as B, portfolio, store  # noqa: E402

store.init()


def test_totp_rfc6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"            # RFC 6238 test key "12345678901234567890"
    assert B.totp(secret, t=59, digits=8) == "94287082" and B.totp(secret, t=1111111109, digits=8) == "07081804"
    assert B.totp("gezd gnbv gy3t qojq gezd gnbv gy3t qojq", t=59) == "287082"


def test_symbols():
    assert B.norm_symbol("NSE:SBIN-EQ", "IN") == "SBIN" and B.norm_symbol("SBIN-EQ", "IN") == "SBIN"
    assert B.norm_symbol("brk.b", "US") == "US:BRK-B"


def test_zerodha_upstox_fyers_angel_dhan_formats():
    z = B.parse_zerodha({"status": "success", "data": [{"tradingsymbol": "GOLDBEES", "exchange": "BSE", "isin": "INF204KB17I5",
                                                         "quantity": 2, "t1_quantity": 1, "average_price": 40.67, "last_price": 42.47}]})
    assert z[0]["symbol"] == "GOLDBEES" and z[0]["qty"] == 3 and z[0]["avg"] == 40.67 and z[0]["ltp"] == 42.47
    u = B.parse_upstox({"status": "success", "data": [{"isin": "INE528G01035", "company_name": "YES BANK LTD.", "quantity": 36, "exchange": "NSE",
                                                         "tradingsymbol": "YESBANK", "last_price": 17.05, "average_price": 18.75,
                                                         "instrument_token": "NSE_EQ|INE528G01035"}]})
    assert u[0]["symbol"] == "YESBANK" and u[0]["name"] == "YES BANK LTD." and u[0]["qty"] == 36
    f = B.parse_fyers({"s": "ok", "holdings": [{"symbol": "NSE:SBIN-EQ", "quantity": 10, "remainingQuantity": 10, "costPrice": 500.5,
                                                "ltp": 571.1, "pl": 706, "marketVal": 5711, "isin": "INE062A01020"}],
                       "overall": {"count_total": 1}})
    assert f[0]["symbol"] == "SBIN" and f[0]["avg"] == 500.5 and f[0]["isin"] == "INE062A01020"
    a = B.parse_angel({"status": True, "data": {"holdings": [{"tradingsymbol": "SBIN-EQ", "exchange": "NSE", "isin": "INE062A01020",
                                                               "quantity": 2, "averageprice": 111.87, "ltp": 130.15, "profitandloss": 37.0}]}})
    assert a[0]["symbol"] == "SBIN" and a[0]["qty"] == 2 and a[0]["ltp"] == 130.15
    d = B.parse_dhan([{"exchange": "ALL", "tradingSymbol": "HDFC", "securityId": "1330", "isin": "INE001A01036", "totalQty": 1000,
                       "dpQty": 1000, "t1Qty": 0, "availableQty": 1000, "avgCostPrice": 2655.0}])
    assert d[0]["symbol"] == "HDFC" and d[0]["avg"] == 2655.0 and d[0]["ltp"] is None


def test_us_formats():
    al = B.parse_alpaca([{"symbol": "AAPL", "qty": "10", "avg_entry_price": "150.5", "current_price": "180.1", "asset_class": "us_equity"},
                         {"symbol": "BTCUSD", "qty": "1", "avg_entry_price": "1", "asset_class": "crypto"}])
    assert [h["symbol"] for h in al] == ["US:AAPL"] and al[0]["qty"] == 10
    t1 = B.parse_tradier({"positions": {"position": {"symbol": "MSFT", "quantity": 4, "cost_basis": 1200}}})
    tn = B.parse_tradier({"positions": "null"})
    assert t1[0]["avg"] == 300 and tn == []
    s = B.parse_schwab([{"securitiesAccount": {"positions": [
        {"longQuantity": 5, "shortQuantity": 0, "averagePrice": 100, "marketValue": 600, "instrument": {"symbol": "NVDA", "assetType": "EQUITY"}},
        {"longQuantity": 1, "averagePrice": 2, "marketValue": 3, "instrument": {"symbol": "NVDA 261218C00100000", "assetType": "OPTION"}}]}}])
    assert len(s) == 1 and s[0]["ltp"] == 120 and s[0]["symbol"] == "US:NVDA"


def test_holdings_file_csv_and_excel():
    zerodha_console = b"Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.,Day chg.\nRELIANCE,10,2400,2900,29000,5000,20%,1%\nTCS,2,3500,4100,8200,1200,17%,0%\nTotal,,,,37200,6200,,\n"
    r = B.parse_file(zerodha_console, "holdings.csv", "IN")
    assert [(h["symbol"], h["qty"], h["avg"], h["ltp"]) for h in r] == [("RELIANCE", 10, 2400, 2900), ("TCS", 2, 3500, 4100)]
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Holdings statement as on 15-11-2026"]); ws.append([]); ws.append(["Client: XX"])
    ws.append(["Stock Name", "ISIN", "Quantity", "Average buy price", "Closing price"])
    ws.append(["Gravita India Ltd", "INE024L01027", 25, 1310.5, 1498.0])
    buf = io.BytesIO(); wb.save(buf)
    g = B.parse_file(buf.getvalue(), "groww.xlsx", "IN")
    assert g[0]["qty"] == 25 and g[0]["avg"] == 1310.5 and g[0]["isin"] == "INE024L01027"
    us = B.parse_file(b"Symbol,Quantity,Average Cost\nAAPL,3,150\n", "positions.csv", "US")
    assert us[0]["symbol"] == "US:AAPL"
    try:
        B.parse_file(b"a,b\n1,2\n", "x.csv", "IN")
        raise AssertionError("should fail")
    except B.BrokerError:
        pass


def test_config_masking_and_forget():
    B.configure("zerodha", {"api_key": "key1", "api_secret": "supersecret99"})
    st = {b["id"]: b for b in B.status("http://127.0.0.1:8600")}
    z = st["zerodha"]
    assert z["configured"] and z["fields"][1]["value"].endswith("et99") and "supersecret" not in z["fields"][1]["value"]
    assert z["redirect_uri"] == "http://127.0.0.1:8600/api/broker/zerodha/callback"
    B.configure("zerodha", {"api_key": "key1", "api_secret": "••••••et99"})      # masked = unchanged
    assert B._cfg("zerodha")["api_secret"] == "supersecret99"
    B.forget("zerodha")
    assert not B._cfg("zerodha")


def test_portfolio_merge_and_xray():
    for bid in ("zerodha", "dhan"):
        B.callback(bid, {}, "http://x") if bid == "zerodha" else B.direct_login(bid)
        B.sync(bid)
    x = portfolio.xray("IN")
    tc = next(r for r in x["rows"] if r["symbol"] == "TESTCO")
    assert tc["qty"] == 60 and sorted(tc["brokers"]) == ["Dhan", "Zerodha"] and tc["value"] == 60 * 1450
    sm = x["summary"]
    assert sm["count"] == 4 and abs(sum(r["weight"] for r in x["rows"]) - 100) < 0.1 and sm["pnl"] is not None
    assert "TESTCO" in sm["unscored"]


def test_funds_are_not_scored():
    from app.portfolio import is_fund
    assert is_fund("NIFTYBEES") and is_fund("GOLDBEES") and is_fund("SGBAUG28")
    assert is_fund("US:SPY", "SPDR S&P 500 ETF Trust")
    assert not is_fund("TCS", "Tata Consultancy Services") and not is_fund("ETERNAL", "Eternal Ltd")


def test_check_keys_catches_autofilled_email_and_spaces():
    B.configure("zerodha", {"api_key": "someone@gmail.com", "api_secret": "abc def"})
    r = B.check("zerodha", "http://192.168.31.21:8600")
    got = {x["what"]: x for x in r["checks"]}
    assert not r["ok"] and "e-mail" in got["API key"]["msg"] and "spaces" in got["API secret"]["msg"]
    assert "http://192.168.31.21:8600/api/broker/zerodha/callback" in got["Redirect URL"]["msg"]
    B.configure("zerodha", {"api_key": "kitekey123", "api_secret": "secret456"})
    assert B.check("zerodha", "http://x")["ok"]
    r = B.check("dhan", "http://x")                      # token broker: keys missing, so it is not asked
    assert not r["ok"] and not any(x["what"].startswith("Asked") for x in r["checks"])
    B.forget("zerodha")


def test_login_valid_until_uses_the_brokers_stated_time():
    from datetime import datetime
    from app import calendars
    t = datetime(2026, 11, 28, 9, 15, tzinfo=calendars.IST).timestamp()
    assert B.valid_until("zerodha", t) == "2026-11-29T06:00+05:30"
    assert B.valid_until("upstox", t) == "2026-11-29T03:30+05:30"
    early = datetime(2026, 11, 28, 2, 0, tzinfo=calendars.IST).timestamp()
    assert B.valid_until("upstox", early) == "2026-11-28T03:30+05:30"
    assert B.valid_until("fyers", t) is None               # no exact time published: none shown


def test_file_preview_shows_columns_without_saving():
    csv = b"Instrument,Qty.,Avg. cost,LTP\nTESTCO,10,100,120\nTESTBANK,5,50,55\n"
    store.put_company("PORTFOLIO::file", {"rows": [], "broker": "File", "filename": "old.csv"})
    p = B.preview_file(csv, "h.csv", "IN")
    assert p["count"] == 2 and p["columns"]["symbol"] == "Instrument" and p["columns"]["quantity"] == "Qty."
    assert p["sample"][0]["symbol"] == "TESTCO" and store.get_company("PORTFOLIO::file")[1]["filename"] == "old.csv"


def test_portfolio_history_is_saved_once_a_day():
    store.put_company("PFHIST::IN", {"days": {"2026-11-20": {"value": 1000.0, "invested": 900.0}}})
    h = portfolio._history("IN", 1100.0, 950.0)
    assert h["since"] == "2026-11-20" and h["points"][-1]["value"] == 1100.0 and len(h["points"]) == 2
    h = portfolio._history("IN", 1200.0, 950.0)            # same day again: replaced, not added
    assert len(h["points"]) == 2 and h["points"][-1]["value"] == 1200.0


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
