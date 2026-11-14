"""Central settings for EquityLens. Override any value with an environment variable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
DATA_DIR = Path(os.getenv("EQL_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "equitylens.sqlite3"
STATIC_DIR = BASE_DIR / "static"                            # prebuilt frontend

SOURCE_BASE = "https://www.screener.in"

# How long a fetched company page is reused before fetching again (hours)
CACHE_TTL_HOURS = float(os.getenv("EQL_CACHE_TTL_HOURS", "24"))

# Universe scan politeness: seconds between companies (plus random jitter)
SCAN_DELAY_SECONDS = float(os.getenv("EQL_SCAN_DELAY", "3.0"))
# Skip a company in a scan if it was fetched within this many hours
SCAN_REUSE_HOURS = float(os.getenv("EQL_SCAN_REUSE_HOURS", "72"))

REQUEST_TIMEOUT = float(os.getenv("EQL_TIMEOUT", "20"))

# Assumptions used by the future-scenario model (all editable)
REQUIRED_RETURN = float(os.getenv("EQL_REQUIRED_RETURN", "0.12"))   # 12% / yr target
FAIR_EXIT_PE = float(os.getenv("EQL_FAIR_EXIT_PE", "20"))            # reverse-DCF exit P/E

HOST = os.getenv("EQL_HOST", "0.0.0.0")
PORT = int(os.getenv("EQL_PORT", "8600"))

# Demo mode: serves built-in sample companies (TESTCO, TESTBANK) without internet.
DEMO = os.getenv("EQL_DEMO", "0") == "1"
FIXTURE_DIR = BASE_DIR / "tests" / "fixtures"
