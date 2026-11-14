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
print("\nALL GOOD" if ok else "\nSOME CHECKS FAILED - send me the output above")
