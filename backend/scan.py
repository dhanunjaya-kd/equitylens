"""Scan the whole universe and fill the Rankings page.

    python scan.py              # full NIFTY 500 (about 40-60 min, polite pacing)
    python scan.py --limit 25   # quick trial on the first 25 stocks
"""
import argparse
import time

from app import service, store

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    store.init()
    t = time.time()
    service.start_scan(limit=args.limit, block=True)
    s = service.scan_status()
    print(f"Done: {s['done']} scanned, {s['failed']} failed, source={s['source']}, {int(time.time()-t)}s")
    for e in s["errors"][-10:]:
        print("  !", e)
