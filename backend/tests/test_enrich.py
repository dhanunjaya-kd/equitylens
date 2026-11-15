"""F&O list + live-field joins (offline):  python tests/test_enrich.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import enrich, store  # noqa: E402

store.init()

MKTLOTS = """UNDERLYING                                        ,SYMBOL    ,NOV-26    ,DEC-26    ,JAN-27    
NIFTY 50                                          ,NIFTY     ,75        ,75        ,75        
NIFTY BANK                                        ,BANKNIFTY ,35        ,35        ,35        
NIFTY MID SELECT                                  ,MIDCPNIFTY,140       ,140       ,140       
Derivatives on Individual Securities              ,Symbol    ,          ,          ,          
AARTI INDUSTRIES LTD                              ,AARTIIND  ,1325      ,1325      ,1325      
BAJAJ FINANCE LIMITED                             ,BAJFINANCE,750       ,750       ,750       
NEWLY ADDED LTD                                   ,NEWCO     ,          ,500       ,500       """


def test_parse_mktlots():
    lots = enrich.parse_fno(MKTLOTS)
    assert lots == {"AARTIIND": 1325, "BAJFINANCE": 750, "NEWCO": 500}


def test_join_fields():
    store.put_company("MOVERS::IN", {"rows": [{"symbol": "AARTIIND", "ret": {"1W": 2.0, "1M": 5.5, "3M": 9.0, "1Y": 20.0},
                                               "above50": True, "above200": False, "from_hi": -3.2, "rvol": 1.8, "new_high": False}]})
    store.put_company("DELIVERY::IN", {"rows": [{"symbol": "AARTIIND", "dp": 62.0, "dq_x": 1.7}]})
    store.put_company("SURV::IN", {"flags": {"BADCO": [{"label": "GSM stage 2", "severity": "high"}]}})
    store.put_company("PIT2::IN::30", {"rows": [
        {"symbol": "AARTIIND", "market": True, "side": "BUY", "value": 2.0, "promoter": True},
        {"symbol": "AARTIIND", "market": True, "side": "SELL", "value": 0.5, "promoter": False},
        {"symbol": "AARTIIND", "market": False, "side": "BUY", "value": 9.0, "promoter": True}]})
    enrich._mem.clear()
    store.put_company("FNO::list", {"lots": {"AARTIIND": 1325}})
    rows = enrich.join_all([{"symbol": "AARTIIND"}, {"symbol": "BADCO"}], "IN")
    a, b = rows
    assert a["fno"] and a["lot"] == 1325 and a["ret_1m"] == 5.5 and a["above50"] and not a["above200"] and a["near_high"] == -3.2
    assert a["dp"] == 62.0 and a["deliv_x"] == 1.7 and a["insider_net"] == 1.5 and a["insider_buying"] and not a["surveillance"]
    assert not b["fno"] and b["surveillance"] and b["surv_labels"] == ["GSM stage 2"] and b["insider_net"] is None and "ret_1m" not in b


def test_us_rows_have_no_fno():
    assert enrich.fno_info("US:AAPL") is None
    r = enrich.join_all([{"symbol": "US:AAPL"}], "US")[0]
    assert "fno" not in r


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
