"""AI layer: research note, stock Q&A chat, document reader, bull-vs-bear
debate and a Top Picks explainer.

Providers (switch in the app's ⚙️ Settings, or in backend/.env):
  * claude  — Anthropic Messages API      (needs ANTHROPIC_API_KEY)
  * openai  — OpenAI Chat Completions API (needs OPENAI_API_KEY)
  * gemini  — Google Gemini API           (needs GEMINI_API_KEY; has a free tier)
  * ollama  — local models via Ollama      (free, runs on your laptop)
  * demo    — offline canned answers, for testing the screens

Every prompt sends only EquityLens's own data for that stock (scores, flags,
financial tables, forensics, valuation, technicals, documents). The model is
told to stay inside that data and say when something isn't in it.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
from typing import Optional

import requests

from . import config, store

SETTINGS_FILE = config.DATA_DIR / "ai_settings.json"
DEFAULTS = {
    "provider": os.getenv("EQL_AI_PROVIDER", "demo" if config.DEMO else "claude"),
    "claude_model": os.getenv("EQL_CLAUDE_MODEL", "claude-sonnet-5-5"),
    "openai_model": os.getenv("EQL_OPENAI_MODEL", "gpt-5.6-terra"),
    "gemini_model": os.getenv("EQL_GEMINI_MODEL", "gemini-3.8-flash"),
    "ollama_model": os.getenv("EQL_OLLAMA_MODEL", "llama3.1:8b"),
    "ollama_url": os.getenv("EQL_OLLAMA_URL", "http://localhost:11434"),
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "max_tokens": int(os.getenv("EQL_AI_MAX_TOKENS", "2500")),
}
SECRET_KEYS = ("anthropic_api_key", "openai_api_key", "gemini_api_key")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class AIError(Exception):
    pass


# ------------------------------------------------------------------ settings
def load_settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).items() if v not in (None, "")})
        except (OSError, json.JSONDecodeError):
            pass
    return s


def save_settings(new: dict) -> dict:
    cur = {}
    if SETTINGS_FILE.exists():
        try:
            cur = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cur = {}
    for k in DEFAULTS:
        if k in new:
            v = new[k]
            if k in SECRET_KEYS and (v is None or "•" in str(v)):
                continue  # masked value sent back unchanged: keep the stored key
            cur[k] = v
    SETTINGS_FILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return public_settings()


def _mask(k: str) -> str:
    return (k[:7] + "•" * 8 + k[-4:]) if k and len(k) > 14 else ("•" * 8 if k else "")


def public_settings() -> dict:
    s = load_settings()
    out = {k: v for k, v in s.items() if k not in SECRET_KEYS}
    out.update({k: _mask(s[k]) for k in SECRET_KEYS})
    out["ready"] = _ready(s)
    return out


def _ready(s: dict) -> bool:
    p = s["provider"]
    return (p in ("demo", "ollama") or (p == "claude" and bool(s["anthropic_api_key"]))
            or (p == "openai" and bool(s["openai_api_key"])) or (p == "gemini" and bool(s["gemini_api_key"])))


def model_label(s: Optional[dict] = None) -> str:
    s = s or load_settings()
    p = s["provider"]
    return {"claude": f"Claude · {s['claude_model']}", "openai": f"OpenAI · {s['openai_model']}", "gemini": f"Gemini · {s['gemini_model']}",
            "ollama": f"Ollama · {s['ollama_model']}", "demo": "Demo (offline)"}.get(p, p)


# ------------------------------------------------------------------ providers
def complete(system: str, messages: list[dict], max_tokens: Optional[int] = None, s: Optional[dict] = None) -> str:
    """messages: [{role: user|assistant, content: str}] -> assistant text"""
    s = s or load_settings()
    mt = max_tokens or s["max_tokens"]
    p = s["provider"]
    if not _ready(s):
        raise AIError(f"No API key set for {p}. Open ⚙️ Settings and add it (or switch to Ollama).")
    try:
        if p == "claude":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
                "x-api-key": s["anthropic_api_key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": s["claude_model"], "max_tokens": mt, "system": system, "messages": messages})
            _raise(r, "Claude")
            return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        if p == "openai":
            r = requests.post("https://api.openai.com/v1/chat/completions", timeout=180, headers={
                "Authorization": f"Bearer {s['openai_api_key']}", "Content-Type": "application/json"},
                json={"model": s["openai_model"], "max_completion_tokens": mt,
                      "messages": [{"role": "system", "content": system}] + messages})
            _raise(r, "OpenAI")
            return (r.json()["choices"][0]["message"].get("content") or "").strip()
        if p == "gemini":
            contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
            r = requests.post(f"{GEMINI_BASE}/models/{s['gemini_model']}:generateContent", timeout=180,
                              headers={"x-goog-api-key": s["gemini_api_key"], "Content-Type": "application/json"},
                              json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                                    "generationConfig": {"maxOutputTokens": mt}})
            _raise(r, "Gemini")
            body = r.json()
            cands = body.get("candidates") or []
            if not cands:
                reason = (body.get("promptFeedback") or {}).get("blockReason", "no answer returned")
                raise AIError(f"Gemini returned no answer ({reason}).")
            return "".join(pt.get("text", "") for pt in (cands[0].get("content") or {}).get("parts", [])).strip()
        if p == "ollama":
            r = requests.post(s["ollama_url"].rstrip("/") + "/api/chat", timeout=600,
                              json={"model": s["ollama_model"], "stream": False, "options": {"num_predict": mt},
                                    "messages": [{"role": "system", "content": system}] + messages})
            _raise(r, "Ollama")
            return (r.json().get("message") or {}).get("content", "").strip()
        if p == "demo":
            return _demo_answer(system, messages)
    except requests.ConnectionError as e:
        hint = " Is Ollama running? Start it with `ollama serve`." if p == "ollama" else ""
        raise AIError(f"Can't reach {p}.{hint} ({e.__class__.__name__})") from e
    except requests.Timeout as e:
        raise AIError(f"{p} took too long to answer. Try again or use a smaller model.") from e
    raise AIError(f"Unknown provider '{p}'")


def list_gemini_models() -> list[str]:
    """Models your Gemini key can use for text generation (newest names first)."""
    s = load_settings()
    if not s["gemini_api_key"]:
        raise AIError("Add your Gemini API key first.")
    r = requests.get(f"{GEMINI_BASE}/models", params={"pageSize": 1000},
                     headers={"x-goog-api-key": s["gemini_api_key"]}, timeout=30)
    _raise(r, "Gemini")
    names = [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
             if "generateContent" in (m.get("supportedGenerationMethods") or []) and "gemini" in m.get("name", "")
             and not any(x in m["name"] for x in ("image", "tts", "embedding", "audio", "live", "robotics"))]
    return sorted(set(names), reverse=True)


def _raise(r: requests.Response, name: str) -> None:
    if r.status_code == 200:
        return
    try:
        body = r.json()
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error") or body
    except ValueError:
        msg = r.text[:300]
    hints = {401: " — the API key is wrong or expired.", 403: " — this key can't use that model.",
             404: " — model name not found; check it in Settings.", 429: " — rate limit or credit exhausted; wait or top up.",
             529: " — the service is overloaded; try again in a minute."}
    raise AIError(f"{name} error {r.status_code}{hints.get(r.status_code, '')} {msg}")


# ------------------------------------------------------------------ context
def _compact_table(t: dict, last: int = 10) -> dict:
    cols = t.get("columns", [])[-last:]
    n = len(t.get("columns", []))
    return {"columns": cols, "rows": {k: v[n - len(cols):] for k, v in t.get("rows", {}).items()}}


def build_context(report: dict, tech: Optional[dict] = None) -> str:
    c, a = report["company"], report["analysis"]
    m = a["metrics"]
    keep_m = {k: v for k, v in m.items() if k not in ("fcf_series", "years") and v is not None}
    proj = a.get("projection", {})
    val = a.get("valuation", {})
    fx = a.get("forensics", {})
    ctx = {
        "company": {"name": c.get("name"), "nse": c.get("nse_symbol"), "bse": c.get("bse_code"),
                    "sector": c.get("sector_path"), "about": c.get("about"), "key_points": (c.get("key_points_md") or c.get("key_points") or "")[:6000],
                    "numbers_basis": report.get("view"), "data_fetched_unix": int(report.get("fetched_at") or 0)},
        "verdict": a["verdict"], "scores_0_100": a["scores"], "metrics": keep_m,
        "strengths": a["strengths"], "red_flags": a["flags"],
        "source_pros": c.get("pros"), "source_cons": c.get("cons"),
        "forensics": {
            "piotroski": {k: fx.get("piotroski", {}).get(k) for k in ("score_9", "zone", "year")} | {
                "failed_checks": [x["name"] for x in fx.get("piotroski", {}).get("checks", []) if x.get("pass") is False]},
            "altman": {k: fx.get("altman", {}).get(k) for k in ("z", "zone", "reason")},
            "beneish": {k: fx.get("beneish", {}).get(k) for k in ("m", "zone", "reason")},
            "dupont_last_years": (fx.get("dupont") or [])[-5:],
        },
        "valuation": {"fair_value": val.get("fair_value"), "methods": val.get("methods"),
                      "pe_bands": (val.get("pe_bands") or {}).get("bands"), "ev": val.get("ev"),
                      "median_pe_10y": a.get("median_pe")},
        "ten_year_story": [{"year": t["year"], "events": [e["text"] for e in t["events"]]} for t in a.get("timeline", []) if t["events"]],
        "scenarios": {"assumptions": proj.get("assumptions"), "horizons": proj.get("horizons"),
                      "reverse_dcf": proj.get("reverse_dcf"), "views": a.get("horizons")},
        "tables_rs_crore": {
            "profit_loss": _compact_table(c["tables"]["profit_loss"], 12),
            "quarters": _compact_table(c["tables"]["quarters"], 8),
            "balance_sheet": _compact_table(c["tables"]["balance_sheet"], 6),
            "cash_flow": _compact_table(c["tables"]["cash_flow"], 6),
            "ratios": _compact_table(c["tables"]["ratios"], 6),
            "shareholding_pct": _compact_table(c["tables"]["shareholding_quarterly"], 8),
        },
        "peers": {"rows": (report.get("peers") or {}).get("rows", [])[:8], "median": (report.get("peers") or {}).get("median")},
        "documents": [{"category": g["category"], "items": [i.get("title") for i in g["items"][:5]]} for g in c.get("documents", [])],
    }
    if tech:
        ctx["technicals"] = {"summary": tech.get("summary"), "stats": tech.get("stats"), "levels": tech.get("levels"),
                             "recent_crosses": tech.get("markers", [])[-3:]}
    return json.dumps(ctx, separators=(",", ":"), default=str)


RULES = """You are EquityLens AI, an equity research analyst for Indian listed companies.
Ground rules:
- Use ONLY the data in the <data> block (and any document text provided). If something isn't there, say "not in the data" instead of guessing. Never invent numbers, events, management names or news.
- Money is in ₹ crore unless stated. Percentages are already in %. Quote the actual figures you rely on.
- Be balanced: give real risks as clearly as strengths.
- This is research support, not investment advice. Don't tell the user to buy or sell; describe what the numbers say and what would change the picture.
- Write in clear, simple English for a retail investor. Use short sections, bullet points and **bold** for key numbers. Markdown only, no HTML."""


def _system(report: dict, tech: Optional[dict], extra: str = "") -> str:
    return f"{RULES}\n{extra}\n<data>\n{build_context(report, tech)}\n</data>"


# ------------------------------------------------------------------ features
def _cache_get(key: str, ttl: float) -> Optional[dict]:
    hit = store.get_company(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def research_note(report: dict, tech: Optional[dict], refresh: bool = False) -> dict:
    s = load_settings()
    key = f"AI::NOTE::{report['symbol']}::{model_label(s)}"
    if not refresh and (hit := _cache_get(key, 24 * 3600)):
        return hit
    prompt = """Write a research note on this company with these sections:
## In one paragraph
## Business quality
## Growth: what drove it and can it continue
## Balance sheet & cash flow
## Forensic & accounting checks
## Valuation
## 3 / 5 / 10-year view
(base your view on the scenario numbers; explain what has to go right and what could go wrong)
## Key risks
## What to watch next (5 specific, measurable items, e.g. a margin level or a debt number)
Keep it under 700 words."""
    text = complete(_system(report, tech), [{"role": "user", "content": prompt}], s=s)
    out = {"text": text, "model": model_label(s), "created": time.time()}
    store.put_company(key, out)
    return out


def chat(report: dict, tech: Optional[dict], history: list[dict]) -> dict:
    s = load_settings()
    msgs = [{"role": h["role"], "content": str(h["content"])[:4000]} for h in history[-12:] if h.get("role") in ("user", "assistant")]
    if not msgs or msgs[-1]["role"] != "user":
        raise AIError("Ask a question first.")
    text = complete(_system(report, tech, "Answer the user's question about this company in under 250 words unless they ask for detail."),
                    msgs, max_tokens=1200, s=s)
    return {"text": text, "model": model_label(s)}


def debate(report: dict, tech: Optional[dict], refresh: bool = False) -> dict:
    s = load_settings()
    key = f"AI::DEBATE::{report['symbol']}::{model_label(s)}"
    if not refresh and (hit := _cache_get(key, 24 * 3600)):
        return hit
    bull = complete(_system(report, tech, "ROLE: You are the BULL analyst. Build the strongest honest case FOR owning this stock for 5+ years, using only the data. Acknowledge the single biggest risk at the end."),
                    [{"role": "user", "content": "Make the bull case in 5-7 bullet points with numbers, then one line on the biggest risk. Max 300 words."}], max_tokens=1200, s=s)
    bear = complete(_system(report, tech, "ROLE: You are the BEAR analyst. Build the strongest honest case AGAINST owning this stock for 5+ years, using only the data. Acknowledge the single best counter-argument at the end."),
                    [{"role": "user", "content": "Make the bear case in 5-7 bullet points with numbers, then one line on the best counter-argument. Max 300 words."}], max_tokens=1200, s=s)
    judge = complete(_system(report, tech, "ROLE: You are the neutral JUDGE. Weigh both cases against the data. Point out any claim that the data doesn't support."),
                     [{"role": "user", "content": f"BULL CASE:\n{bull}\n\nBEAR CASE:\n{bear}\n\nWhich case is better supported by the data and why? Then list the 3 facts that would settle the debate. Finish with a line 'Leaning: Bull / Bear / Balanced'. Max 300 words."}],
                     max_tokens=1200, s=s)
    lean = re.search(r"Leaning:\s*\**\s*(Bull|Bear|Balanced)", judge, re.I)
    out = {"bull": bull, "bear": bear, "judge": judge, "leaning": lean.group(1).title() if lean else None,
           "model": model_label(s), "created": time.time()}
    store.put_company(key, out)
    return out


def read_document(report: dict, url: str, title: str = "") -> dict:
    s = load_settings()
    key = f"AI::DOC::{url}::{model_label(s)}"
    if hit := _cache_get(key, 30 * 24 * 3600):
        return hit
    text, pages = fetch_document_text(url)
    if len(text.strip()) < 200:
        raise AIError("Couldn't read text from this document (it may be a scanned image or blocked).")
    limit = 90000 if s["provider"] in ("claude", "openai") else 24000
    clipped = text[:limit]
    note = f"\n[Document truncated: used the first {limit:,} of {len(text):,} characters]" if len(text) > limit else ""
    prompt = f"""Below is the text of "{title or 'a company document'}" ({pages} pages).{note}
Summarise it for an investor:
## What kind of document this is (period covered)
## Key numbers mentioned
## Management guidance & targets (growth, margins, capex, debt, timelines)
## New projects, products, capacity or acquisitions
## Risks, problems or one-offs mentioned
## Tone (confident / cautious / defensive) with a short quote-free explanation
## How this fits with the financial data in <data> (agree / contradict)
Quote numbers exactly as in the document. Max 600 words.

<document>
{clipped}
</document>"""
    out = {"text": complete(_system(report, None), [{"role": "user", "content": prompt}], s=s),
           "model": model_label(s), "pages": pages, "chars": len(text), "created": time.time()}
    store.put_company(key, out)
    return out


def fetch_document_text(url: str) -> tuple[str, int]:
    if config.DEMO:
        return ("Demo document. Revenue grew 12% this year to ₹36,000 crore. Management guides 12-14% volume growth "
                "next year, capex of ₹1,200 crore for a new plant commissioning in Q3 FY27, and net debt to stay near zero. "
                "Raw material prices remain a risk. " * 8), 12
    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
                                                "Referer": "https://www.bseindia.com/"})
    if r.status_code != 200:
        raise AIError(f"Couldn't download the document (HTTP {r.status_code}).")
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype or r.content[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise AIError("PDF reading needs pypdf: run `pip install -r requirements.txt`.") from e
        reader = PdfReader(io.BytesIO(r.content))
        parts = []
        for i, pg in enumerate(reader.pages):
            if i >= 150:
                break
            try:
                parts.append(pg.extract_text() or "")
            except Exception:  # noqa: BLE001 - a bad page shouldn't kill the whole read
                continue
        return re.sub(r"[ \t]+", " ", "\n".join(parts)), len(reader.pages)
    from bs4 import BeautifulSoup
    return BeautifulSoup(r.text, "lxml").get_text(" ", strip=True), 1


def guidance_check(report: dict, refresh: bool = False) -> dict:
    s = load_settings()
    key = f"AI::GUIDE::{report['symbol']}::{model_label(s)}"
    if not refresh and (hit := _cache_get(key, 24 * 3600)):
        return hit
    prompt = """Check management's targets against reality.
1. From key_points (and anything else in <data>), list every forward-looking target or guidance item: growth targets, margin/ROCE targets, capacity, capex, debt, new businesses, timelines.
2. Make a markdown table with columns: Target | What the track record shows (quote the actual numbers from the tables/metrics) | What the base-case scenario assumes | Verdict
   Verdict is one of: ✅ Achievable (track record already supports it), ⚠️ Stretch (needs clear improvement), ❌ Unlikely (contradicts the numbers), ❓ Can't check (data not available).
3. Then ## Overall: is management's ambition supported by its own history? 3-4 sentences.
4. Then ## What to verify next quarter: 3 bullet points with specific numbers to look for.
If no targets are in the data, say so plainly and stop."""
    out = {"text": complete(_system(report, None), [{"role": "user", "content": prompt}], s=s),
           "model": model_label(s), "created": time.time()}
    store.put_company(key, out)
    return out


def explain_chart(report: dict, tech: dict) -> dict:
    s = load_settings()
    o = tech.get("outlook") or {}
    data = {"company": report["company"].get("name"), "interval": tech.get("interval"), "stats": tech.get("stats"),
            "summary": tech.get("summary"), "levels": tech.get("levels"), "recent_crosses": tech.get("markers", [])[-3:],
            "chart_story": o.get("story"), "if_then": o.get("scenarios"), "volatility_range": o.get("cone"),
            "historical_analogs": o.get("analogs"), "setup_today": o.get("setup"),
            "fundamental_verdict": report["analysis"]["verdict"], "business_score": report["analysis"]["scores"].get("business")}
    system = RULES + "\nYou are explaining a stock's price chart to a beginner.\n<data>\n" + json.dumps(data, default=str) + "\n</data>"
    prompt = """Explain this chart in plain English:
## What the chart is saying now
## What happened to reach here
## Next 1-3 months: the levels that matter (use the if/then levels and the volatility range; no predictions, only conditions)
## What history says (use historical_analogs: how often it rose after the same setup, compared with an average day)
## How this fits the fundamentals (one short paragraph)
## Watch-list (3 bullet points with exact price levels)
Max 400 words."""
    return {"text": complete(system, [{"role": "user", "content": prompt}], max_tokens=1500, s=s), "model": model_label(s)}


def explain_picks(rows: list[dict], title: str = "Top Picks") -> dict:
    s = load_settings()
    fields = ("symbol", "name", "sector", "market_cap", "pe", "pb", "roce", "profit_cagr_5", "sales_cagr_5", "debt_to_equity",
              "piotroski", "fair_value_upside", "overall", "business", "valuation", "verdict", "base_5y", "base_10y", "high_flags")
    data = [{k: r.get(k) for k in fields} for r in rows[:15]]
    system = RULES + f"\n<data>\n{json.dumps({'list': title, 'stocks': data}, default=str)}\n</data>"
    prompt = """For each stock in the list, write 2-3 lines: why it ranks here (cite 2-3 numbers) and the main thing to check before trusting the ranking.
Then finish with:
## Patterns
(what these stocks have in common: sectors, valuation, growth, and any concentration risk in the list)
## Before you shortlist
(3 checks the user should do on any of them)"""
    return {"text": complete(system, [{"role": "user", "content": prompt}], s=s), "model": model_label(s)}


# ------------------------------------------------------------------ demo
def _demo_answer(system: str, messages: list[dict]) -> str:
    m = re.search(r"<data>\n(.*)\n</data>", system, re.S)
    try:
        d = json.loads(m.group(1)) if m else {}
    except json.JSONDecodeError:
        d = {}
    comp = d.get("company")
    name = comp.get("name", "This company") if isinstance(comp, dict) else (comp or "This company")
    met = d.get("metrics", {})
    q = messages[-1]["content"]
    if "chart_story" in d:
        story = "\n".join(f"- {x}" for x in (d.get("chart_story") or []))
        return f"## What the chart is saying now\n{story}\n\n_(Demo mode — add an API key in ⚙️ Settings for a real AI explanation.)_"
    if "ROLE: You are the BULL" in system:
        return f"- **{met.get('profit_cagr_5')}%** profit CAGR over 5 years\n- ROCE near **{met.get('roce_avg_5')}%**\n- Almost no debt (D/E **{met.get('debt_to_equity')}**)\n\nBiggest risk: valuation already prices in growth."
    if "ROLE: You are the BEAR" in system:
        return f"- P/E **{met.get('pe')}** needs growth to continue\n- Growth may slow from **{met.get('sales_cagr_5')}%**\n\nBest counter-argument: cash conversion is strong."
    if "ROLE: You are the neutral JUDGE" in system:
        return "The bull case is better supported by the cash-flow and return data; the bear case rests on valuation.\n\nLeaning: Bull"
    if "stocks" in d:
        return "\n".join(f"**{s['symbol']}** ranks on score {s.get('overall')} with ROCE {s.get('roce')}%." for s in d["stocks"]) + "\n\n## Patterns\nDemo answer."
    if "<document>" in q:
        return "## Key numbers mentioned\n- Revenue **₹36,000 crore**, +12%\n## Management guidance\n- 12–14% volume growth, capex **₹1,200 crore**\n_(demo answer)_"
    if "management's targets" in q:
        return "| Target | Track record | Base case | Verdict |\n|---|---|---|---|\n| 12-14% volume growth | Sales grew **12%**/yr over 5 years | 13% | ✅ Achievable |\n\n## Overall\nDemo answer.\n\n_(demo mode)_"
    if "research note" in q.lower():
        return (f"## In one paragraph\n{name} has grown profit **{met.get('profit_cagr_5')}%** a year over 5 years with ROCE around "
                f"**{met.get('roce_avg_5')}%** and almost no debt.\n\n## Key risks\n- Valuation (P/E **{met.get('pe')}**)\n\n_(Demo mode — add an API key in ⚙️ Settings for real AI answers.)_")
    return f"**Demo answer** about {name}: you asked \"{q[:80]}\". In demo mode I only echo the data — P/E **{met.get('pe')}**, ROCE **{met.get('roce_avg_5')}%**."
