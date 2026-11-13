"""Company profile for the Stock page: NSE industry, theme, and a short "what the company does" text.

Industry and theme come from data the desk already has (cache/industry.json, themes.csv).
The description is written once per stock by Google's Gemini API (free tier) and kept in
cache/profiles.json; it needs the GEMINI_API_KEY secret. Without the key only industry and theme
are published. The text is AI-written from the model's general knowledge, so it can be wrong or
out of date: the Stock page says so, and the model is told to answer null when it does not know
the company.

The free tier allows only a limited number of requests a day, so stocks are sent in batches
(largest market cap first) and whatever is left waits for the next evening's run.

Output: site/data/profiles/<letter>.json  {SYM: {"ind": basic industry, "th": theme, "d": text}}
"""
import json
import logging
import os
import re
import time
from datetime import date

import industry

log = logging.getLogger("profiles")
API = "https://generativelanguage.googleapis.com/v1beta"
BATCH = 12                # companies per request
REDO_DAYS = 365           # rewrite a description after this long
UNKNOWN_RETRY_DAYS = 90   # companies the model did not know: ask again after this long
MAX_WORDS = 60


def shard(sym: str) -> str:
    c = (sym or "_")[0].upper()
    return c if "A" <= c <= "Z" else "0"


def _session():
    try:
        from curl_cffi import requests
    except ImportError:  # pragma: no cover
        import requests
    return requests.Session()


def pick_model(s, key):
    """GEMINI_MODEL if set; otherwise the newest Flash-Lite, then Flash, model the key can use
    (model names change every few months, so they are not hard-coded)."""
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced.replace("models/", "")]
    r = s.get(f"{API}/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"model list: HTTP {r.status_code} {r.text[:200]}")
    names = [m["name"].replace("models/", "") for m in r.json().get("models", [])
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    names = [n for n in names if n.startswith("gemini-") and "flash" in n
             and not re.search(r"image|tts|audio|live|preview|exp|embedding|omni|thinking|computer", n)]

    def ver(n):
        m = re.match(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0
    lite = sorted([n for n in names if "lite" in n], key=ver, reverse=True)
    flash = sorted([n for n in names if "lite" not in n], key=ver, reverse=True)
    out = lite[:2] + flash[:2]
    if not out:
        raise RuntimeError("no Gemini Flash model is available to this key")
    return out


PROMPT = """You write short factual company notes for an Indian stock-market research page.

For each NSE-listed company below, write what the business does: its main products or services,
its main customers or end markets, and anything notable about its position (for example
"largest", "state-owned", "subsidiary of ..."). Rules:
- 2 sentences, at most 45 words, plain English, present tense.
- Facts about the business only. No share price, valuation, recent results, forecasts, opinions
  or advice. No words like "leading" unless it is a verifiable market position.
- The NSE industry is given as a hint. If you are not confident you know this specific company
  (do not guess from the name or the industry), return null for it.

Reply with JSON only: an object mapping each symbol to its text or null.

Companies:
"""


def ask(s, key, model, batch):
    """batch: [(sym, name, industry)] -> {sym: text or None}. Raises Quota on HTTP 429."""
    lines = "\n".join(f"{sym} | {name} | {ind or 'industry not known'}" for sym, name, ind in batch)
    body = {"contents": [{"parts": [{"text": PROMPT + lines}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    r = s.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key, "Content-Type": "application/json"},
               data=json.dumps(body), timeout=90)
    if r.status_code == 429:
        raise Quota(r.text[:300])
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    cands = r.json().get("candidates") or []
    text = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""
    return parse_reply(text, [b[0] for b in batch])


class Quota(Exception):
    pass


def tidy(text):
    """One clean paragraph, or None if it is not usable."""
    if not isinstance(text, str):
        return None
    t = re.sub(r"\s+", " ", re.sub(r"[*_`#]", "", text)).strip()
    if len(t) < 30 or re.search(r"\b(i do not|i don't|not confident|no information|unable to|cannot confirm|as an ai)\b", t, re.I):
        return None
    words = t.split(" ")
    if len(words) > MAX_WORDS:                      # cut at the last full sentence inside the limit
        cut = " ".join(words[:MAX_WORDS])
        t = cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rstrip(",;:") + "…"
    return t


def parse_reply(text, syms):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise RuntimeError("reply was not JSON")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise RuntimeError("reply was not a JSON object")
    return {s: tidy(data.get(s)) for s in syms if s in data}


def describe(order, names, ind_map, cache, minutes, save):
    """Fill cache[sym] = {"d": text or None, "on": date, "m": model} for stocks that need it."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        log.info("profiles: GEMINI_API_KEY not set; publishing industry and theme only")
        return "no key"
    today = date.today()

    def due(sym):
        r = cache.get(sym)
        if not r or not r.get("on"):
            return True
        age = (today - date.fromisoformat(r["on"])).days
        return age >= (REDO_DAYS if r.get("d") else UNKNOWN_RETRY_DAYS)
    todo = [s for s in order if names.get(s) and due(s)]
    if not todo:
        return "up to date"
    s = _session()
    try:
        models = pick_model(s, key)
    except Exception as e:  # noqa: BLE001
        log.warning("profiles: %s", e)
        print(f"::warning title=Company profiles::{e}"[:300])
        return "error"
    log.info("profiles: %d stocks to describe, models %s", len(todo), models)
    end = time.time() + minutes * 60
    done = wrote = errors = 0
    mi = 0
    status = "ok"

    def ask_any(batch):
        """Ask the current model; when its free allowance is used up (per minute or per day),
        wait once, then move to the next model. Raises Quota when every model is exhausted."""
        nonlocal mi
        while True:
            for wait in (0, 40):
                time.sleep(wait)
                try:
                    return ask(s, key, models[mi], batch)
                except Quota:
                    pass
            mi += 1
            if mi >= len(models):
                raise Quota()

    for i in range(0, len(todo), BATCH):
        if time.time() > end:
            status = "out of time"
            break
        batch = [(x, names[x], (ind_map.get(x) or {}).get("basic") or (ind_map.get(x) or {}).get("industry")) for x in todo[i:i + BATCH]]
        try:
            got = ask_any(batch)
        except Quota:
            status = "free limit reached for today"
            break
        except Exception as e:  # noqa: BLE001
            log.warning("profiles: %s", e)
            errors += 1
            if errors >= 4:
                status = "error"
                break
            continue
        for sym, _, _ in batch:
            if sym in got:
                cache[sym] = {"d": got[sym], "on": today.isoformat(), "m": models[mi]}
                wrote += bool(got[sym])
                done += 1
        save()
        time.sleep(5)       # stay under the free tier's requests-per-minute limit
    left = len([x for x in todo if due(x)])
    log.info("profiles: %d asked, %d described, %d left (%s)", done, wrote, left, status)
    print(f"::notice title=Company profiles::{done} stocks asked, {wrote} described, {left} left for later runs ({status})")
    return status


def build(order, names, data_dir, cache_dir, jload, jsave, minutes=8.0):
    """order: symbols, largest market cap first. names: {sym: company name}."""
    ind_map = jload(os.path.join(cache_dir, "industry.json"), {})
    _, lookup = industry.load_themes()
    cache_path = os.path.join(cache_dir, "profiles.json")
    cache = jload(cache_path, {})
    if minutes > 0:
        describe(order, names, ind_map, cache, minutes, lambda: jsave(cache_path, cache))
    shards = {}
    for sym in set(ind_map) | set(cache):
        info = ind_map.get(sym) or {}
        ind = info.get("basic") or info.get("industry")
        theme = industry.theme_of(info, None, lookup) if ind else None
        row = {}
        if ind:
            row["ind"] = ind
        if theme and theme != ind:
            row["th"] = theme
        d = (cache.get(sym) or {}).get("d")
        if d:
            row["d"] = d
        if row:
            shards.setdefault(shard(sym), {})[sym] = row
    out_dir = os.path.join(data_dir, "profiles")
    for k, rows in shards.items():
        jsave(os.path.join(out_dir, f"{k}.json"), dict(sorted(rows.items())))
    log.info("profiles: %d stocks published (%d with a description)", sum(len(v) for v in shards.values()),
             sum(1 for v in shards.values() for r in v.values() if r.get("d")))
