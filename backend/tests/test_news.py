"""News (offline):  python tests/test_news.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import news, store  # noqa: E402

store.init()

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Markets</title>
<item><title>Sensex, Nifty end higher as banks gain</title><link>https://example.com/a</link>
<description><![CDATA[<p>Benchmarks rose for a <b>third</b> day.</p>]]></description><pubDate>Sun, 22 Nov 2026 10:49:16 +0530</pubDate></item>
<item><title>Horoscope today: what the stars say</title><link>https://example.com/b</link><pubDate>Sun, 22 Nov 2026 09:00:00 +0530</pubDate></item>
<item><title>No date item</title><link>https://example.com/c</link></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>
<entry><title>8-K - APPLE INC (0000320193) (Filer)</title><link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/320193/x-index.htm"/>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-11-20 &lt;b&gt;AccNo:&lt;/b&gt; 0000320193-26-000101 &lt;b&gt;Size:&lt;/b&gt; 300 KB
&lt;br&gt;Item 2.02: Results of Operations and Financial Condition
&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary><updated>2026-11-20T16:31:04-05:00</updated></entry>
<entry><title>8-K - SMALL CO (0000999999) (Filer)</title><link href="https://www.sec.gov/x"/><summary>Item 2.02: Results</summary><updated>2026-11-20T16:00:00-05:00</updated></entry>
<entry><title>8-K - APPLE INC (0000320193) (Filer)</title><link href="https://www.sec.gov/y"/><summary>Item 7.01: Regulation FD Disclosure Item 9.01: Exhibits</summary><updated>2026-11-20T17:00:00-05:00</updated></entry>
</feed>"""


def test_rss_and_atom_are_read_with_times():
    a = news.parse_feed(RSS)
    assert [x["title"] for x in a] == ["Sensex, Nifty end higher as banks gain", "Horoscope today: what the stars say"]
    assert a[0]["summary"] == "Benchmarks rose for a third day." and a[0]["time"] == "2026-11-22T05:19:16+00:00"
    b = news.parse_feed(ATOM)
    assert b[0]["url"].endswith("x-index.htm") and b[0]["time"] == "2026-11-20T21:31:04+00:00"
    assert news.parse_feed("not xml") == []


def test_only_market_news_is_kept():
    keep = lambda t, syms=(), mo=False: news._keep({"title": t, "summary": "", "symbols": list(syms)}, mo)
    assert keep("Sensex, Nifty end higher as banks gain") == "markets"
    assert keep("RBI keeps repo rate unchanged at 5.5%") == "economy"
    assert keep("Oil prices climb as OPEC+ extends output cuts") == "global"
    assert keep("Infosys Q2 net profit rises 8%", ["INFY"]) == "results"
    assert keep("Horoscope today: what the stars say") is None
    assert keep("5 stocks to buy this week for big gains", ["INFY"]) is None             # tip lists are dropped
    assert keep("Five celebrity homes you must see") is None
    assert keep("Bollywood star launches clothing line") is None


def test_filings_keep_market_moving_ones_only():
    data = [
        {"symbol": "RVNL", "desc": "Award of Order / Receipt of Order", "attchmntText": "Rail Vikas Nigam Limited has emerged as the lowest bidder "
         "for a project worth INR 3,48,48,79,130.87.", "an_dt": "22-Nov-2026 14:03:21", "sm_name": "Rail Vikas Nigam Limited", "seq_id": "1"},
        {"symbol": "ABC", "desc": "Trading Window", "attchmntText": "Closure of trading window", "an_dt": "22-Nov-2026 13:00:00", "sm_name": "ABC Ltd"},
        {"symbol": "XYZ", "desc": "Copy of Newspaper Publication", "attchmntText": "Newspaper copies", "an_dt": "22-Nov-2026 12:00:00", "sm_name": "XYZ"},
        {"symbol": "DEF", "desc": "Change in Directorate", "attchmntText": "Appointment of an independent director", "an_dt": "22-Nov-2026 11:00:00"},
        {"symbol": "GHI", "desc": "Change in Management", "attchmntText": "Resignation of the Chief Executive Officer (CEO)", "an_dt": "22-Nov-2026 10:00:00"},
        {"symbol": "JKL", "desc": "Dividend", "attchmntText": "Interim dividend of Rs 5 per share; record date fixed", "an_dt": "22-Nov-2026 09:00:00"},
    ]
    got = news.parse_nse_announcements(json.dumps(data))
    assert {g["symbols"][0]: g["category"] for g in got} == {"RVNL": "orders", "GHI": "management", "JKL": "actions"}
    r = next(g for g in got if g["symbols"] == ["RVNL"])
    assert r["time"] == "2026-11-22T08:33:21+00:00" and r["kind"] == "filing"


def test_order_amounts_in_crore():
    assert news.order_crore("project worth INR 3,48,48,79,130.87") == 348.49
    assert news.order_crore("estimated order size Rs. 27,02,56,350/-") == 27.03
    assert news.order_crore("an order of ₹1,250 crore") == 1250
    assert news.order_crore("orders worth Rs 450 lakh") == 4.5
    assert news.order_crore("Rs 25 per share") is None                                     # no unit, too small: not an order size


def test_sec_8k_keeps_sp500_and_moving_items():
    got = news.parse_sec_8k(ATOM, {320193: "AAPL"})
    assert len(got) == 1                                                                   # small co not tracked; FD-only filing dropped
    assert got[0]["symbols"] == ["US:AAPL"] and got[0]["category"] == "results" and "Results of operations" in got[0]["title"]


def test_tagger_is_unambiguous():
    tag = news.build_tagger({"MARUTI": "Maruti Suzuki India Ltd", "ADANIPORTS": "Adani Ports and Special Economic Zone Ltd",
                             "ADANIENT": "Adani Enterprises Ltd", "RVNL": "Rail Vikas Nigam Ltd", "US:TGT": "Target Corp"})
    assert tag("Maruti Suzuki raises prices of select models") == ["MARUTI"]
    assert tag("Adani shares rally") == []                                                  # "Adani" fits two companies: not used
    assert tag("Adani Ports bags new terminal") == ["ADANIPORTS"]
    assert tag("RVNL emerges L1 bidder") == ["RVNL"]
    assert tag("Brokerage raises target price on banks") == []                              # common word, lower case


def test_same_story_shown_once_with_every_source():
    t = "2026-11-22T05:00:00+00:00"
    items = [{"id": "1", "kind": "news", "title": "Sensex, Nifty end higher as banks gain; FPIs buy for third day", "time": t,
              "symbols": [], "source": "A", "url": "a"},
             {"id": "2", "kind": "news", "title": "Sensex, Nifty end higher as banks gain, FPIs buy for a third day", "time": t,
              "symbols": [], "source": "B", "url": "b"},
             {"id": "3", "kind": "news", "title": "Oil prices climb as OPEC+ extends cuts", "time": t, "symbols": [], "source": "A", "url": "c"}]
    out = news.cluster(items)
    assert len(out) == 2
    assert [s["name"] for s in out[0]["sources"]] == ["A", "B"]


def test_payload_in_demo():
    d = news.get("IN")
    assert d["count"] >= 4 and all(i["market"] in ("IN", "GLOBAL") for i in d["items"])
    m = next(i for i in d["items"] if i["category"] == "markets")
    assert m["covered"] == 2                                                                # two demo publishers, one story
    o = next(i for i in d["items"] if i["category"] == "orders")
    assert o["order"]["crore"] == 1250
    u = news.get("US")
    assert any(i["symbols"] == ["US:TSTUS"] for i in u["items"]) and all(i["market"] in ("US", "GLOBAL") for i in u["items"])


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
