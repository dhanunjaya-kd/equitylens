"""Run once after setup: checks the live data source end to end.

    python selftest.py            # tests RELIANCE, HDFCBANK, ITC
    python selftest.py TCS INFY   # or your own symbols
"""
import sys
import traceback

from app import scraper, service, store

store.init()
ok = True
print("1) Search 'reliance' ...", end=" ")
try:
    r = scraper.search("reliance")
    print("OK" if r else "EMPTY", [x["symbol"] for x in r[:3]])
except Exception as e:
    ok = False
    print("FAILED:", e)

for sym in (sys.argv[1:] or ["RELIANCE", "HDFCBANK", "ITC"]):
    print(f"2) Full report {sym} ...", end=" ")
    try:
        rep = service.build_report(sym, refresh=True)
        c, a = rep["company"], rep["analysis"]
        m = a["metrics"]
        pl = c["tables"]["profit_loss"]
        print("OK")
        print(f"   {c['name']} | view={rep['view']} | years={len(pl['columns'])} | rows={len(pl['rows'])}")
        print(f"   price={m['price']} pe={m['pe']} mcap={m['market_cap']} roce5={m['roce_avg_5']} roe5={m['roe_avg_5']}")
        print(f"   sales5={m['sales_cagr_5']}% profit5={m['profit_cagr_5']}% promoter={m['promoter_latest']}% median_pe={a['median_pe']}")
        print(f"   peers={len((rep['peers'] or {}).get('rows', []))} price_pts={len((rep['price_chart'] or {}).get('Price', []))}")
        print(f"   scores={a['scores']}")
        print(f"   verdict={a['verdict']['label']}")
        if rep["extras_errors"]:
            print("   optional parts missing:", rep["extras_errors"])
        empty = [k for k, v in c["tables"].items() if not v["rows"]]
        if empty:
            print("   empty sections:", empty)
    except Exception:
        ok = False
        print("FAILED")
        traceback.print_exc()
print("3) US stock (SEC EDGAR + Yahoo): AAPL ...", end=" ")
try:
    rep = service.build_report("US:AAPL", refresh=True)
    m = rep["analysis"]["metrics"]
    print("OK")
    print(f"   {rep['company']['name']} | years={len(rep['company']['tables']['profit_loss']['columns'])} | "
          f"price=${m['price']} pe={m['pe']} mcap=${m['market_cap']}M | verdict={rep['analysis']['verdict']['label']}")
except Exception:
    ok = False
    print("FAILED (set EQL_SEC_USER_AGENT='Your Name your@email.com' in backend/.env)")
    traceback.print_exc()
print("4) Calendars (Nasdaq earnings + economy, NSE results, official schedules) ...")
try:
    from app import calendars
    from datetime import datetime
    today = datetime.now(calendars.IST).date()
    for mk in ("US", "IN"):
        e = calendars.earnings(mk, today, 7)
        c = calendars.economy(mk, today, 7)
        res = [r for r in e["rows"] if r["type"] in ("Earnings", "Results")]
        live = [x for x in c["events"] if not x.get("official")]
        print(f"   {mk}: results this week={len(res)} (e.g. {[r['name'] for r in res[:3]]}) | economic events={len(c['events'])} "
              f"(live {len(live)}) | notes={e['notes'] + c['notes']}")
        if not res or not live:
            print("   ⚠️ one source returned nothing — send me this output")
except Exception:
    ok = False
    print("   FAILED")
    traceback.print_exc()
print("5) Index card ...", end=" ")
try:
    from app import indices
    for mk in ("IN", "US"):
        print(" | ".join(f"{i['name']} {i.get('price')} ({i.get('change_pct')}%)" if i.get("price") else f"{i['name']} ERROR {i.get('error')}" for i in indices.get(mk)["items"]))
except Exception:
    ok = False
    print("FAILED")
    traceback.print_exc()
print("6) Smart money (NSE delivery, deals, insider, surveillance · SEC Form 4) ...")
try:
    from app import flows
    for label, fn in (("delivery", lambda: (lambda d: f"{d['date']} rows={len(d['rows'])}")(flows.delivery())),
                      ("bulk/block deals", lambda: (lambda d: f"{d['date']} deals={len(d['rows'])}")(flows.deals())),
                      ("insider trades (30d)", lambda: (lambda d: f"rows={len(d['rows'])} e.g. {d['rows'][:1]}")(flows.insiders_in(30))),
                      ("surveillance", lambda: (lambda d: f"{d['date']} flagged={len(d['flags'])}")(flows.surveillance())),
                      ("SEC Form 4 AAPL", lambda: (lambda d: f"rows={len(d['rows'])} summary={d['summary']}")(flows.insiders_us("US:AAPL")))):
        try:
            print(f"   {label}: {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"   {label}: FAILED {e}")
except Exception:
    ok = False
    traceback.print_exc()
print("7) F&O stock list ...", end=" ")
try:
    from app import enrich
    lots = enrich.fno()
    print(f"{len(lots)} stocks, e.g. {dict(list(lots.items())[:3])}")
    if len(lots) < 100:
        print("   ⚠️ expected ~200 F&O stocks — send me this output")
except Exception:
    ok = False
    print("FAILED")
    traceback.print_exc()
print("8) Logos ...", end=" ")
try:
    from app import logos
    got = {s: logos.get(s)[1] for s in ("RELIANCE", "TCS", "US:AAPL", "US:MSFT")}
    print(got, "(svg = initials fallback, png/jpg/ico = real logo)")
except Exception:
    ok = False
    print("FAILED")
    traceback.print_exc()
print("\nALL GOOD" if ok else "\nSOME CHECKS FAILED - send me the output above")
