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


def test_nse_report_list_finds_surveillance_file():
    import json
    sample = {"CurrentDay": [
        {"fileKey": "CM-BHAVDATA-FULL", "displayName": "Full Bhavcopy and Security Deliverable data", "fileActlName": "sec_bhavdata_full_13112026.csv",
         "filePath": "https://nsearchives.nseindia.com/products/content/", "tradingDate": "13-Nov-2026"},
        {"fileKey": "CM-REG-IND", "displayName": "Surveillance Indicator (csv)", "fileActlName": "REG1_IND13112026.csv",
         "filePath": "https://nsearchives.nseindia.com/content/cm/", "tradingDate": "13-Nov-2026"}],
        "PreviousDay": [{"fileKey": "CM-REG-IND", "displayName": "Surveillance Indicator (csv)", "fileActlName": "REG1_IND12112026.csv",
                         "filePath": "https://nsearchives.nseindia.com/content/cm/"}]}
    old = flows._nse_text
    flows._nse_text = lambda url, params=None, headers=None: json.dumps(sample)
    try:
        files = flows.report_files()
        assert {"name": "REG1_IND13112026.csv", "url": "https://nsearchives.nseindia.com/content/cm/REG1_IND13112026.csv",
                "group": "CurrentDay", "title": "Surveillance Indicator (csv)"} in files
        urls = flows.surveillance_report_urls()
        assert urls[0].endswith("/content/cm/REG1_IND13112026.csv") and len(urls) == 2
    finally:
        flows._nse_text = old


def test_insider_fetch_falls_back_to_other_request_shapes():
    calls = []
    old_json, old_sess = flows._pit_json, flows.calendars._nse_session

    class S:
        def get(self, *a, **k):
            return None
    flows.calendars._nse_session = lambda: S()

    def fake(params):
        calls.append(dict(params))
        return [{"symbol": "ABC"}] if params == {"index": "equities"} else []
    flows._pit_json = fake
    try:
        from datetime import date
        j = flows.pit_fetch(date(2026, 10, 14), date(2026, 11, 13))
        assert j["data"] == [{"symbol": "ABC"}] and len(calls) == 2          # date range empty -> latest list used
        flows._pit_json = lambda params: calls.append(params) or []
        calls.clear()
        j = flows.pit_fetch(date(2026, 10, 14), date(2026, 11, 13))
        assert j["data"] == [] and len(calls) == 3 + 5                      # 3 shapes, then 7-day windows over 30 days
    finally:
        flows._pit_json, flows.calendars._nse_session = old_json, old_sess


def test_pit_gg_records_are_normalised():
    rec = {"symbol": "GRAVITA", "companyName": "Gravita India Limited", "nameOfThePerson": "Rajat Agrawal",
           "categoryOfPerson": "Promoters", "typeOfSecurity": "Equity Shares", "noOfSecurities": "25000",
           "valueOfSecurity": "37450000", "transactionType": "Buy", "modeOfAcquisition": "Market Purchase",
           "dateOfAllotmentFrom": "10-Nov-2026", "broadcastDateTime": "12-Nov-2026 18:42:10", "xbrlLink": "https://x/y.xml"}
    n = flows.pit_normalise(rec)
    rows = flows.parse_pit({"data": [n]})
    r = rows[0]
    assert r["symbol"] == "GRAVITA" and r["person"] == "Rajat Agrawal" and r["promoter"] and r["side"] == "BUY"
    assert r["market"] and r["qty"] == 25000 and r["value"] == 3.745 and r["date"] == "2026-11-10"
    classic = {"symbol": "ABC", "secAcq": "1"}
    assert flows.pit_normalise(classic) is classic


def test_peers_new_layouts():
    from app import parser
    # header as the first <tr> of <tbody>, an S.No. column, and a median row
    html = """<table class="data-table"><tbody>
      <tr><th>S.No.</th><th>Name</th><th>CMP Rs.</th><th>P/E</th><th>Mar Cap Rs.Cr.</th></tr>
      <tr><td>1.</td><td><a href="/company/GRAVITA/consolidated/">Gravita India</a></td><td>1,498</td><td>27.8</td><td>11,056</td></tr>
      <tr><td>2.</td><td><a href="/company/POCL/">Pondy Oxides</a></td><td>842</td><td>31.2</td><td>2,350</td></tr>
      <tr><td></td><td>Median: 2 Co.</td><td>1,170</td><td>29.5</td><td>6,703</td></tr></tbody></table>"""
    p = parser.parse_peers(html)
    assert [r["symbol"] for r in p["rows"]] == ["GRAVITA", "POCL"]
    assert p["rows"][0]["P/E"] == 27.8 and p["rows"][1]["CMP Rs."] == 842 and p["median"]["P/E"] == 29.5
    # <thead> and no S.No. column
    html2 = """<table><thead><tr><th>Name</th><th>P/E</th></tr></thead><tbody>
      <tr><td><a href="/company/TCS/">TCS</a></td><td>22.1</td></tr></tbody></table>"""
    p2 = parser.parse_peers(html2)
    assert p2["rows"] == [{"name": "TCS", "symbol": "TCS", "P/E": 22.1}]


PIT_XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/pit">
  <xbrli:context id="MainI"><xbrli:entity><xbrli:identifier scheme="x">GRAVITA</xbrli:identifier></xbrli:entity></xbrli:context>
  <xbrli:context id="Person1"/><xbrli:context id="Person2"/>
  <in-capmkt:NameOfTheCompany contextRef="MainI">Gravita India Limited</in-capmkt:NameOfTheCompany>
  <in-capmkt:Symbol contextRef="MainI">GRAVITA</in-capmkt:Symbol>
  <in-capmkt:NameOfThePerson contextRef="Person1">Rajat Agrawal</in-capmkt:NameOfThePerson>
  <in-capmkt:CategoryOfPerson contextRef="Person1">Promoters</in-capmkt:CategoryOfPerson>
  <in-capmkt:TypeOfSecurityAcquiredOrDisposed contextRef="Person1">Equity Shares</in-capmkt:TypeOfSecurityAcquiredOrDisposed>
  <in-capmkt:NumberOfSecuritiesAcquiredOrDisposed contextRef="Person1" unitRef="shares" decimals="0">25000</in-capmkt:NumberOfSecuritiesAcquiredOrDisposed>
  <in-capmkt:ValueOfSecuritiesAcquiredOrDisposed contextRef="Person1" unitRef="INR" decimals="0">37450000</in-capmkt:ValueOfSecuritiesAcquiredOrDisposed>
  <in-capmkt:TransactionType contextRef="Person1">Buy</in-capmkt:TransactionType>
  <in-capmkt:ModeOfAcquisitionOrDisposal contextRef="Person1">Market Purchase</in-capmkt:ModeOfAcquisitionOrDisposal>
  <in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesFrom contextRef="Person1">2026-11-10</in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesFrom>
  <in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesTo contextRef="Person1">2026-11-11</in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesTo>
  <in-capmkt:DateOfIntimationToCompany contextRef="Person1">2026-11-12</in-capmkt:DateOfIntimationToCompany>
  <in-capmkt:PercentageOfShareholdingPreTransaction contextRef="Person1" unitRef="pure" decimals="2">31.20</in-capmkt:PercentageOfShareholdingPreTransaction>
  <in-capmkt:PercentageOfShareholdingPostTransaction contextRef="Person1" unitRef="pure" decimals="2">31.24</in-capmkt:PercentageOfShareholdingPostTransaction>
  <in-capmkt:NameOfThePerson contextRef="Person2">Yogesh Malhotra</in-capmkt:NameOfThePerson>
  <in-capmkt:CategoryOfPerson contextRef="Person2">Key Managerial Personnel</in-capmkt:CategoryOfPerson>
  <in-capmkt:NumberOfSecuritiesAcquiredOrDisposed contextRef="Person2" unitRef="shares" decimals="0">1200</in-capmkt:NumberOfSecuritiesAcquiredOrDisposed>
  <in-capmkt:ValueOfSecuritiesAcquiredOrDisposed contextRef="Person2" unitRef="INR" decimals="0">1800000</in-capmkt:ValueOfSecuritiesAcquiredOrDisposed>
  <in-capmkt:TransactionType contextRef="Person2">Sell</in-capmkt:TransactionType>
  <in-capmkt:ModeOfAcquisitionOrDisposal contextRef="Person2">Market Sale</in-capmkt:ModeOfAcquisitionOrDisposal>
  <in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesFrom contextRef="Person2">2026-11-09</in-capmkt:DateOfAllotmentAdviceAcquisitionOfSharesSaleOfSharesFrom>
</xbrli:xbrl>"""


def test_pit_xbrl_filing():
    recs = flows.parse_pit_xbrl(PIT_XBRL)
    assert [r["acqName"] for r in recs] == ["Rajat Agrawal", "Yogesh Malhotra"]
    rows = flows.parse_pit({"data": [{"symbol": "GRAVITA", "company": "Gravita India Limited", **r} for r in recs]})
    a, b = rows
    assert a["side"] == "BUY" and a["promoter"] and a["market"] and a["qty"] == 25000 and a["value"] == 3.745
    assert a["date"] == "2026-11-10" and a["before_pct"] == 31.2 and a["after_pct"] == 31.24
    assert b["side"] == "SELL" and not b["promoter"] and b["qty"] == 1200 and b["date"] == "2026-11-09"


def test_filing_list_expanded_from_cache_and_queued():
    url = "https://nsearchives.nseindia.in/corporate/xbrl/IT_1_WebXMLFile_x.xml"
    store.put_company(flows._xml_key(url), {"rows": flows.parse_pit_xbrl(PIT_XBRL)})
    lst = [{"symbol": "GRAVITA", "companyName": "Gravita India Limited", "broadcastDateTime": "12-Nov-2026 18:42:10", "xmlFileName": url},
           {"symbol": "XYZ", "companyName": "Xyz Ltd", "broadcastDateTime": "13-Nov-2026 10:00:00",
            "xmlFileName": "https://nsearchives.nseindia.in/corporate/xbrl/IT_2_not_cached.xml"}]
    old = flows._fill_queue
    flows._fill_queue = lambda: None                      # don't touch the network in tests
    try:
        recs, waiting = flows.expand_filings(lst, budget=0)
    finally:
        flows._fill_queue = old
        flows._xq.clear(); flows._xq_running[0] = False
    rows = flows.parse_pit({"data": recs})
    assert waiting == 1 and [r["person"] for r in rows if r["symbol"] == "GRAVITA"] == ["Rajat Agrawal", "Yogesh Malhotra"]
    x = next(r for r in rows if r["symbol"] == "XYZ")
    assert x["type"] == "Filing (details loading)" and x["side"] == "OTHER" and x["date"] == "2026-11-13"


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
