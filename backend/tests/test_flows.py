"""Smart-money data on the official file formats (offline):  python tests/test_flows.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import flows, store  # noqa: E402

store.init()

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
ZOTA, EQ, 04-Jun-2021, 183.75, 184.00, 184.00, 160.00, 172.95, 173.60, 174.48, 121798, 212.51, 1813, 74813, 61.43
GOLDBEES, EQ, 04-Jun-2021, 44.10, 44.20, 44.30, 44.00, 44.20, 44.21, 44.15, 100, 0.05, 1, 100, 100.00
NCDXYZ, N1, 04-Jun-2021, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 10, 0.10, 1, -, -
NODEL, BE, 04-Jun-2021, 10, 10, 10, 10, 10, 10.5, 10, 500, 0.05, 3, -, -"""


def test_bhavcopy_delivery():
    r = flows.parse_bhav(BHAV)
    assert set(r) == {"ZOTA", "GOLDBEES", "NODEL"}                       # debt series skipped
    z = r["ZOTA"]
    assert z["dp"] == 61.43 and z["dq"] == 74813 and z["qty"] == 121798 and z["turnover"] == 2.13 and z["prev"] == 183.75
    assert r["NODEL"]["dp"] is None and r["NODEL"]["dq"] is None


def test_delivery_lists():
    rows = [{"symbol": "A", "ret": 3, "dp": 70, "dq_x": 3, "turnover": 50, "in_index": True, "deliv_value": 10},
            {"symbol": "B", "ret": -2, "dp": 65, "dq_x": 2, "turnover": 50, "in_index": True, "deliv_value": 5},
            {"symbol": "C", "ret": 4, "dp": 30, "dq_x": 4, "turnover": 50, "in_index": True, "deliv_value": 1},
            {"symbol": "D", "ret": 4, "dp": 80, "dq_x": 4, "turnover": 1, "in_index": True, "deliv_value": 1},
            {"symbol": "E", "ret": 4, "dp": 80, "dq_x": 4, "turnover": 50, "in_index": False, "deliv_value": 1}]
    L = flows.delivery_lists({"rows": rows})
    assert [r["symbol"] for r in L["buying"]] == ["A"] and [r["symbol"] for r in L["selling"]] == ["B"]
    assert "E" in [r["symbol"] for r in flows.delivery_lists({"rows": rows}, only_index=False)["buying"]]


DEALS = """Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks
13-Nov-2026,ABC,ABC Ltd,SBI MUTUAL FUND,BUY,"1,500,000",412.35,-
13-Nov-2026,XYZ,XYZ Ltd,SOME LLP,SELL,250000,99.10,-
bad,,,,,,,"""


def test_bulk_block_deals():
    d = flows.parse_deals(DEALS, "bulk")
    assert len(d) == 2 and d[0]["side"] == "BUY" and d[0]["qty"] == 1500000 and d[0]["value"] == 61.85 and d[0]["date"] == "2026-11-13"
    assert d[1]["side"] == "SELL" and d[1]["client"] == "SOME LLP"


def test_insider_pit_format():
    j = {"data": [
        {"symbol": "ABC", "company": "ABC Ltd", "acqName": "Promoter Trust", "personCategory": "Promoter Group", "secType": "Equity Shares",
         "secAcq": "10000", "secVal": "5000000", "tdpTransactionType": "Buy", "acqMode": "Market Purchase", "acqfromDt": "10-Nov-2026",
         "intimDt": "12-Nov-2026 18:01", "befAcqSharesPer": "60.1", "afterAcqSharesPer": "60.2"},
        {"symbol": "ABC", "company": "ABC Ltd", "acqName": "CFO", "personCategory": "Key Managerial Personnel", "secType": "Equity Shares",
         "secAcq": "2000", "secVal": "1000000", "tdpTransactionType": "Sell", "acqMode": "Market Sale", "acqfromDt": "11-Nov-2026"},
        {"symbol": "ABC", "acqName": "Promoter", "personCategory": "Promoters", "secType": "Equity Shares", "secAcq": "50000",
         "secVal": "0", "tdpTransactionType": "Pledge Creation", "acqMode": "-", "acqfromDt": "11-Nov-2026"},
        {"symbol": "ABC", "secType": "Warrants", "secAcq": "1", "tdpTransactionType": "Buy", "acqfromDt": "11-Nov-2026"}]}
    r = flows.parse_pit(j)
    assert len(r) == 3
    assert r[0]["side"] == "BUY" and r[0]["promoter"] and r[0]["market"] and r[0]["value"] == 0.5 and r[0]["price"] == 500 and r[0]["date"] == "2026-11-10"
    assert r[1]["side"] == "SELL" and not r[1]["promoter"] and r[2]["side"] == "PLEDGE"
    s = flows.summarise(r)
    assert s["buys"] == 1 and s["sells"] == 1 and s["net_value"] == 0.4 and s["pledges"] == 1


def test_surveillance_reg_ind_spec():
    text = flows._demo_reg_ind()                                     # header exactly as NSE's published structure
    f = flows.parse_reg_ind(text)
    labels = {s: [x["label"] for x in v] for s, v in f.items()}
    assert ["GSM stage 2"] in labels.values()
    assert any("Long-term ASM stage 1" in v and "Loss-making for 8+ quarters" in v for v in labels.values())
    assert any("High promoter pledge (surveillance)" in v for v in labels.values())
    assert len(f) == 3                                               # rows with all 100s are not flagged


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
 <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
 <reportingOwner><reportingOwnerId><rptOwnerName>COOK TIMOTHY D</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>true</isDirector><isOfficer>true</isOfficer><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
 <nonDerivativeTable>
  <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle><transactionDate><value>2026-10-02</value></transactionDate>
   <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>S</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>129963</value></transactionShares><transactionPricePerShare><value>257.66</value></transactionPricePerShare>
   <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
   <postTransactionAmounts><sharesOwnedFollowingTransaction><value>3280295</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
  <nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate>
   <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>200000</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare>
   <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
 </nonDerivativeTable>
</ownershipDocument>"""


def test_sec_form4():
    r = flows.parse_form4(FORM4)
    assert len(r) == 2
    assert r[0]["person"] == "COOK TIMOTHY D" and r[0]["role"] == "Director, Chief Executive Officer" and r[0]["side"] == "SELL"
    assert r[0]["market"] and r[0]["value"] == round(129963 * 257.66 / 1e6, 3) and r[0]["owned_after"] == 3280295
    assert r[1]["type"] == "Option exercise" and not r[1]["market"] and r[1]["value"] is None


def test_stock_bundles_both_markets():
    i = flows.for_stock("TESTCO")
    assert not i["errors"] and i["delivery"]["series"] and "summary" in i["insiders"] and isinstance(i["surveillance"], list)
    u = flows.for_stock("US:TSTUS")
    assert not u["errors"] and u["insiders"]["rows"] and "net_value" in u["insiders"]["summary"]


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
