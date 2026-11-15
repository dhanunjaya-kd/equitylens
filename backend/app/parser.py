"""Turns a public company page into clean, structured numbers.

Output shape (all money in Rs crore unless the row says otherwise):
{
  name, symbol, bse_code, nse_symbol, about, website, sector_path: [..],
  ratios: {"market_cap": 123.0, "current_price": .., "high": .., "low": .., "pe": .., ...},
  tables: {
     "profit_loss":   {"columns": ["Mar 2015", ..., "TTM"], "rows": {"Sales": [..], ...}},
     "balance_sheet": {...}, "cash_flow": {...}, "ratios": {...}, "quarters": {...},
     "shareholding_quarterly": {...}, "shareholding_yearly": {...}
  },
  growth: {"Compounded Sales Growth": {"10 Years": 9.0, "5 Years": ..}, ...},
  pros: [..], cons: [..],
  company_id, warehouse_id, is_financial
}
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def to_number(text) -> Optional[float]:
    if text is None:
        return None
    t = str(text).replace("\xa0", " ").replace("₹", "").replace("Rs.", "").strip()
    if t in ("", "-", "--", "NA", "N/A", "—"):
        return None
    m = _NUM_RE.search(t.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def clean_label(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"\s*\+\s*$", "", t.strip())
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _text(el: Optional[Tag]) -> str:
    return el.get_text(" ", strip=True) if el else ""


def parse_data_table(table: Optional[Tag]) -> dict:
    """Generic Screener-style table: first column = row label, rest = periods."""
    if table is None:
        return {"columns": [], "rows": {}}
    head_cells = table.select("thead th") or (table.find("tr").find_all(["th", "td"]) if table.find("tr") else [])
    columns = [clean_label(_text(c)) for c in head_cells][1:]
    rows: dict[str, list] = {}
    body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
    for tr in body_rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = clean_label(_text(cells[0]))
        if not label or label.lower().startswith("raw pdf"):
            continue
        values = [to_number(_text(c)) for c in cells[1:]]
        if all(v is None for v in values):
            continue
        # keep length aligned with columns
        if columns and len(values) != len(columns):
            values = (values + [None] * len(columns))[: len(columns)]
        if label in rows:
            label = f"{label} ({len(rows)})"
        rows[label] = values
    return {"columns": columns, "rows": rows}


def _section_table(soup: BeautifulSoup, section_id: str) -> Optional[Tag]:
    sec = soup.find(id=section_id)
    if not sec:
        return None
    t = sec.select_one("table.data-table")
    if t:
        return t
    for t in sec.find_all("table"):
        if "ranges-table" not in (t.get("class") or []):
            return t
    return None


def _to_md(el: Tag) -> str:
    """Rich 'key points' block -> light markdown (paragraphs, bold), citation marks removed."""
    el = BeautifulSoup(str(el), "lxml")
    for sup in el.find_all("sup"):
        sup.decompose()
    for b in el.find_all(["strong", "b"]):
        t = b.get_text(" ", strip=True)
        b.replace_with(f"**{t}**" if t else "")
    for br in el.find_all("br"):
        br.replace_with("\n")
    blocks = []
    for p in el.find_all(["p", "li", "h3", "h4"]):
        t = re.sub(r"[ \t]+", " ", p.get_text("", strip=False)).strip()
        t = re.sub(r"\s*\n\s*", "\n", t)
        if t:
            blocks.append(("- " + t) if p.name == "li" else t)
    if not blocks:
        blocks = [re.sub(r"\s+", " ", el.get_text(" ", strip=True))]
    return "\n\n".join(blocks)[:12000]


def _parse_top_ratios(soup: BeautifulSoup) -> dict:
    out: dict = {}
    keymap = {
        "market cap": "market_cap",
        "current price": "current_price",
        "stock p/e": "pe",
        "book value": "book_value",
        "dividend yield": "dividend_yield",
        "roce": "roce",
        "roe": "roe",
        "face value": "face_value",
        "industry pe": "industry_pe",
        "debt to equity": "debt_to_equity",
        "promoter holding": "promoter_holding",
        "pledged percentage": "pledged",
        "eps": "eps",
        "price to book value": "pb",
    }
    for li in soup.select("#top-ratios li"):
        name = clean_label(_text(li.select_one(".name"))).lower()
        nums = [to_number(_text(n)) for n in li.select(".number")]
        nums = [n for n in nums if n is not None]
        if not name:
            continue
        if name.startswith("high / low") or name == "high / low":
            if len(nums) >= 2:
                out["high"], out["low"] = nums[0], nums[1]
            continue
        key = keymap.get(name, re.sub(r"[^a-z0-9]+", "_", name).strip("_"))
        if nums:
            out[key] = nums[0]
    return out


def _parse_growth_tables(soup: BeautifulSoup) -> dict:
    out: dict = {}
    for t in soup.select("table.ranges-table"):
        title = clean_label(_text(t.find("th")))
        vals = {}
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                k = clean_label(_text(tds[0])).rstrip(":")
                vals[k] = to_number(_text(tds[1]))
        if title:
            out[title] = vals
    return out


def _parse_list(soup: BeautifulSoup, selector: str) -> list[str]:
    return [clean_label(_text(li)) for li in soup.select(selector) if _text(li)]


def parse_company(html: str, symbol: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    info = soup.find(id="company-info") or soup.find(attrs={"data-warehouse-id": True})
    company_id = info.get("data-company-id") if info else None
    warehouse_id = info.get("data-warehouse-id") if info else None

    name = _text(soup.find("h1"))

    about = ""
    for sel in (".company-profile .about p", "div.about p", ".about"):
        el = soup.select_one(sel)
        if el and _text(el):
            about = _text(el)
            break
    kp_el = soup.select_one(".company-profile .commentary") or soup.select_one(".commentary")
    key_points = _text(kp_el) if kp_el else ""
    key_points_md = _to_md(kp_el) if kp_el else ""

    bse_code = nse_symbol = website = None
    for a in soup.select(".company-links a, a[href]"):
        t = _text(a)
        if t.startswith("BSE:") and not bse_code:
            bse_code = t.split(":", 1)[1].strip()
        elif t.startswith("NSE:") and not nse_symbol:
            nse_symbol = t.split(":", 1)[1].strip()
    site = soup.select_one(".company-links a[target=_blank]")
    if site and site.get("href", "").startswith("http") and "bseindia" not in site["href"] and "nseindia" not in site["href"]:
        website = site["href"]

    sector_path = []
    for a in soup.select('#peers a[href^="/market/"]'):
        t = _text(a)
        if t and t not in sector_path:
            sector_path.append(t)

    tables = {
        "quarters": parse_data_table(_section_table(soup, "quarters")),
        "profit_loss": parse_data_table(_section_table(soup, "profit-loss")),
        "balance_sheet": parse_data_table(_section_table(soup, "balance-sheet")),
        "cash_flow": parse_data_table(_section_table(soup, "cash-flow")),
        "ratios": parse_data_table(_section_table(soup, "ratios")),
        "shareholding_quarterly": parse_data_table(soup.select_one("#quarterly-shp table")),
        "shareholding_yearly": parse_data_table(soup.select_one("#yearly-shp table")),
    }
    if not tables["shareholding_quarterly"]["rows"]:
        tables["shareholding_quarterly"] = parse_data_table(_section_table(soup, "shareholding"))

    pl_rows = {k.lower() for k in tables["profit_loss"]["rows"]}
    bs_rows = {k.lower() for k in tables["balance_sheet"]["rows"]}
    is_financial = any("financing profit" in r for r in pl_rows) or any(r.startswith("deposits") for r in bs_rows) \
        or ("revenue" in pl_rows and "sales" not in pl_rows and "interest" in pl_rows)

    return {
        "name": name or symbol,
        "symbol": (nse_symbol or symbol or "").upper(),
        "bse_code": bse_code,
        "nse_symbol": nse_symbol,
        "website": website,
        "about": about,
        "key_points": key_points,
        "key_points_md": key_points_md,
        "sector_path": sector_path,
        "ratios": _parse_top_ratios(soup),
        "tables": tables,
        "growth": _parse_growth_tables(soup),
        "pros": _parse_list(soup, ".pros li"),
        "documents": _parse_documents(soup),
        "cons": _parse_list(soup, ".cons li"),
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "is_financial": bool(is_financial),
    }


def _abs(url: str) -> str:
    return "https://www.screener.in" + url if url and url.startswith("/") else url


def _parse_documents(soup: BeautifulSoup) -> list[dict]:
    """Annual reports, concalls, announcements, credit ratings -> [{category, items:[...]}]."""
    sec = soup.find(id="documents")
    if not sec:
        return []
    out = []
    blocks = sec.select(".documents") or [h.parent for h in sec.find_all("h3")]
    for blk in blocks:
        h = blk.find(["h3", "h2"])
        cat = clean_label(_text(h))
        if not cat:
            continue
        items = []
        for li in blk.select("li"):
            links = [a for a in li.find_all("a") if a.get("href")]
            if not links:
                continue
            if len(links) == 1 and "concall-link" not in (links[0].get("class") or []):
                a = links[0]
                sub_el = a.find("div")
                sub = _text(sub_el)
                if sub_el:
                    sub_el.extract()
                items.append({"title": _text(a), "sub": sub, "url": _abs(a["href"]), "links": []})
            else:
                date_el = li.find("div", recursive=False)
                items.append({"title": _text(date_el) or cat, "sub": "", "url": None,
                              "links": [{"label": _text(a) or "Link", "url": _abs(a["href"])} for a in links]})
            if len(items) >= 15:
                break
        if items:
            out.append({"category": cat, "items": items})
    return out


def parse_peers(html: str) -> dict:
    """Peers table -> {"columns": [...], "rows": [{col: value}], "median": {...}}

    Works whether the header is a <thead> or the first <tr> of <tbody>, with or without an S.No. column:
    each company row is found by its /company/ link, and numbers are matched to header cells by position."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return {"columns": [], "rows": [], "median": {}}
    trs = table.find_all("tr")
    header_tr = next((tr for tr in trs if tr.find("th")), trs[0] if trs else None)
    if header_tr is None:
        return {"columns": [], "rows": [], "median": {}}
    columns = [clean_label(_text(th)) for th in header_tr.find_all(["th", "td"])]
    skip = {"s.no.", "s.no", "#", "sno", ""}
    rows, median = [], {}
    for tr in trs:
        if tr is header_tr:
            continue
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        link = tr.find("a", href=re.compile(r"^/company/"))
        texts = [_text(c) for c in cells]
        is_median = any("median" in t.lower() for t in texts[:3])
        if not link and not is_median:
            continue
        rec = {}
        if link:
            rec["name"] = _text(link)
            m = re.match(r"^/company/([^/]+)/", link["href"])
            if m:
                rec["symbol"] = m.group(1).upper()
        # align cells to columns from the right (numbers are the last columns in both layouts)
        offset = len(cells) - len(columns)
        for i, col in enumerate(columns):
            j = i + offset
            if j < 0 or j >= len(cells) or col.lower() in skip or "name" in col.lower():
                continue
            if link and cells[j].find("a", href=re.compile(r"^/company/")):
                continue
            rec[col] = to_number(texts[j])
        if is_median:
            median = {k: v for k, v in rec.items() if k not in ("name", "symbol")}
        elif rec.get("name"):
            rows.append(rec)
    return {"columns": [c for c in columns if c.lower() not in skip], "rows": rows, "median": median}


def parse_chart(data: dict) -> dict:
    """Chart JSON -> {metric: [[date, value], ...]}"""
    out = {}
    for ds in (data or {}).get("datasets", []):
        metric = ds.get("metric") or ds.get("label")
        vals = []
        for pair in ds.get("values", []):
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            v = to_number(pair[1])
            if v is not None:
                vals.append([pair[0], v])
        if metric:
            out[metric] = vals
    return out
