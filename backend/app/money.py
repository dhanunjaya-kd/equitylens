"""Currency context: Indian stocks are in ₹ crore, US stocks in $ million.
Set once per request/company; text generators read it."""
import contextvars

_cur = contextvars.ContextVar("eql_currency", default=("₹", "Cr"))


def market_of(symbol: str) -> str:
    return "US" if (symbol or "").upper().startswith("US:") else "IN"


def set_market(market: str) -> None:
    _cur.set(("$", "M") if market == "US" else ("₹", "Cr"))


def sym() -> str:
    return _cur.get()[0]


def unit() -> str:
    return _cur.get()[1]


def big(v: float) -> str:
    """₹1,234 Cr / $1,234 M"""
    return f"{sym()}{v:,.0f} {unit()}"
