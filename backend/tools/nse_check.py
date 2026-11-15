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
from app import calendars, flows, parser, scraper, universe  # noqa: E402


def show(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def get(url: str, params=None):
    try:
        r = calendars._nse_session().get(url, params=params, timeout=25)
        return r.status_code, r.headers.get("content-type", ""), r.text
    except Exception as e:  # noqa: BLE001
        return None, "", f"ERROR {e.__class__.__name__}: {e}"


show("1) NSE insider trades (api/corporates-pit, last 30 days)")
end = flows._today()
start = end - timedelta(days=30)
st, ct, text = get("https://www.nseindia.com/api/corporates-pit",
                   {"index": "equities", "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
print(f"status={st} type={ct} length={len(text)}")
print("first 300 chars:", text[:300].replace("\n", " "))
try:
    j = json.loads(text)
    data = j if isinstance(j, list) else j.get("data") or []
    print("top-level keys:", list(j.keys())[:15] if isinstance(j, dict) else f"list of {len(j)}")
    print("records:", len(data))
    if data:
        print("first record:", json.dumps(data[0])[:900])
    rows = flows.parse_pit(j)
    print(f"parsed rows: {len(rows)} | with a date: {sum(1 for r in rows if r['date'])}")
except Exception as e:  # noqa: BLE001
    print("not JSON:", e)

show("2) NSE surveillance file (REG_IND), last 3 weekdays")
d, n = flows._today(), 0
while n < 3:
    if d.weekday() < 5:
        n += 1
        for url in flows.surveillance_urls(d):
            st, ct, text = get(url)
            print(f"{st}  {url.rsplit('/', 1)[1]:28s} {len(text):>8} bytes  {text[:60]!r}")
    d -= timedelta(days=1)

show("3) screener.in peers for GRAVITA")
try:
    html = scraper.fetch_company_html("GRAVITA") if hasattr(scraper, "fetch_company_html") else None
except Exception as e:  # noqa: BLE001
    html = None
    print("company page error:", e)
if html is None:
    try:
        from app import service
        rep = service.get_payload("GRAVITA", full=True, max_age_h=0)[0]
        comp = rep["company"]
        print("company_id:", comp.get("company_id"), "| warehouse_id:", comp.get("warehouse_id"))
        print("peers rows:", len((rep["extras"].get("peers") or {}).get("rows", [])), "| errors:", rep["extras"].get("errors"))
        wid = comp.get("warehouse_id")
    except Exception as e:  # noqa: BLE001
        wid = None
        print("report error:", e)
else:
    c = parser.parse_company(html) if hasattr(parser, "parse_company") else {}
    wid = c.get("warehouse_id")
    print("warehouse_id:", wid)
if wid:
    try:
        ph = scraper.fetch_peers_html(wid)
        print(f"peers html: {len(ph)} chars, tables: {ph.count('<table')}")
        print("first 400 chars:", ph[:400].replace("\n", " "))
        print("parsed peers:", len(parser.parse_peers(ph)["rows"]))
    except Exception as e:  # noqa: BLE001
        print("peers fetch error:", e)
else:
    print("no warehouse id found on the company page")

show("4) NIFTY 500 list")
for code in ("N50", "N100", "N500"):
    try:
        print(code, len(universe.index_list(code)))
    except Exception as e:  # noqa: BLE001
        print(code, "error:", e)
print("\nDone. Copy everything above and send it.")
