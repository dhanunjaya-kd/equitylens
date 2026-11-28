"""Run every offline test:  python run_tests.py"""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).parent
tests_dir = root / "tests"
files = sorted(p.name for p in tests_dir.glob("test_*.py"))
env = {**os.environ, "PYTHONPATH": str(root)}
total = failed = 0
for f in files:
    r = subprocess.run([sys.executable, str(tests_dir / f)], capture_output=True, text=True, env=env)
    passed = r.stdout.count("PASS ")
    total += passed
    if r.returncode:
        failed += 1
        print(f"✗ {f}\n{r.stdout[-800:]}{r.stderr[-1500:]}")
    else:
        print(f"✓ {f}: {passed} passed")
print(f"\n{'ALL GOOD' if not failed else 'FAILURES'} — {total} tests passed")
sys.exit(1 if failed else 0)
