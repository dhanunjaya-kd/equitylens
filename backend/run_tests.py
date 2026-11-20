"""Run every offline test:  python run_tests.py"""
import subprocess
import sys
from pathlib import Path

files = ["test_engine.py", "test_stress.py", "test_api.py", "test_ai.py", "test_us.py", "test_movers.py", "test_calendar.py", "test_indices.py", "test_flows.py", "test_enrich.py", "test_universe.py", "test_brokers.py", "test_access.py", "test_premarket.py", "test_accounts.py"]
total = failed = 0
for f in files:
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "tests" / f)], capture_output=True, text=True)
    passed = r.stdout.count("PASS ")
    total += passed
    if r.returncode:
        failed += 1
        print(f"✗ {f}\n{r.stdout[-800:]}{r.stderr[-1500:]}")
    else:
        print(f"✓ {f}: {passed} passed")
print(f"\n{'ALL GOOD' if not failed else 'FAILURES'} — {total} tests passed")
sys.exit(1 if failed else 0)
