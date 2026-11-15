"""Show exactly what NSE and screener.in send back, for the parts that come back empty.

    python tools\\nse_check.py

Copy everything it prints and send it. Nothing is changed or saved.
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import calendars, flows, parser, scraper, service, universe  # noqa: E402


def show(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def get(url: str, params=None, headers=None):
    try:
        r = calendars._nse_session().get(url, params=params, headers=headers, timeout=25)
        return r.status_code, r.text
    except Exception as e:  # noqa: BLE001
        return None, f"ERROR {e.__class__.__name__}: {e}"


end = flows._today()
start = end - timedelta(days=30)

show("1) NSE insider trades: each way of asking")
get(flows.PIT_PAGE)
for label, params in flows.pit_variants(start, end):
    st, text = get(flows.PIT_API, params, {"Referer": flows.PIT_PAGE})
    try:
        j = json.loads(text)
        data = j if isinstance(j, list) else j.get("data") or []
        print(f"{label:34s} status={st} records={len(data)}")
        if data:
            print("   first record:", json.dumps(data[0])[:700])
    except Exception:  # noqa: BLE001
        print(f"{label:34s} status={st} not JSON: {text[:120]!r}")
try:
    j = flows.pit_fetch(start, end)
    rows = flows.parse_pit(j)
    print(f"EquityLens result: {len(j['data'])} records -> {len(rows)} trades, {sum(1 for r in rows if r['date'])} with a date")
except Exception as e:  # noqa: BLE001
    print("EquityLens result: error", e)

show("2) NSE 'All reports' list (where the surveillance file lives now)")
try:
    files = flows.report_files("CM")
    print(f"{len(files)} files listed")
    for f in files:
        if any(k in (f["name"] + f["title"]).upper() for k in ("REG", "SURV", "IND")):
            print(f"   {f['group']:12s} {f['name']:30s} {f['title'][:40]:40s} {f['url']}")
    if files and not any("REG" in f["name"].upper() for f in files):
        print("   (no REG_IND file in the list; all names:)")
        for f in files[:60]:
            print(f"   {f['group']:12s} {f['name']:34s} {f['title'][:50]}")
except Exception as e:  # noqa: BLE001
    print("error:", e)
    st, text = get(flows.REPORTS_API, {"key": "CM"}, {"Referer": "https://www.nseindia.com/all-reports"})
    print(f"raw: status={st} {text[:400]!r}")
try:
    sv = flows.surveillance()
    print(f"EquityLens result: {len(sv['flags'])} flagged stocks, file date {sv['date']}")
except Exception as e:  # noqa: BLE001
    print("EquityLens result:", e)

show("3) screener.in peers for GRAVITA")
try:
    rep = service.get_payload("GRAVITA", refresh=True)[0]
    comp = rep["company"]
    wid = comp.get("warehouse_id")
    print("company_id:", comp.get("company_id"), "| warehouse_id:", wid)
    print("peers rows in report:", len((rep["extras"].get("peers") or {}).get("rows", [])), "| errors:", rep["extras"].get("errors"))
    if wid:
        ph = scraper.fetch_peers_html(wid)
        print(f"peers reply: {len(ph)} chars, <table> count: {ph.count('<table')}")
        print("first 500 chars:", ph[:500].replace("\n", " "))
        print("parsed peers:", len(parser.parse_peers(ph)["rows"]))
    else:
        html, view = scraper.fetch_company_html("GRAVITA")
        i = html.find("warehouse")
        print("no warehouse id. Page text around 'warehouse':", html[max(0, i - 200):i + 300].replace("\n", " ") if i >= 0 else "(word not on the page)")
        j = html.find("peers")
        print("around 'peers':", html[max(0, j - 200):j + 300].replace("\n", " ") if j >= 0 else "(word not on the page)")
except Exception as e:  # noqa: BLE001
    print("error:", e.__class__.__name__, e)

show("4) Stock lists")
for code in ("N50", "N100", "N500"):
    try:
        print(code, len(universe.index_list(code)))
    except Exception as e:  # noqa: BLE001
        print(code, "error:", e)
print("\nDone. Copy everything above and send it.")
