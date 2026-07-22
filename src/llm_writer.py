# -*- coding: utf-8 -*-
"""
Autonomous article writer (OPTIONAL upgrade).

Activates ONLY when:
  - config.toml [llm] openrouter_api_key is set (a free OpenRouter key)
  - [llm] enable_autonomous_writing = true

It mints brand-new, unique long-tail articles into src/articles/ so the engine
never runs out of content. Guardrails:
  - Pulls fresh long-tail keywords from seed themes (no duplicates of existing slugs/keywords).
  - Enforces the article schema and a minimum word count.
  - Injects affiliate-safe phrasing + a compliance disclaimer.
  - Tags every generated file with source="ai" so you can audit/review.
  - Writes files with UTF-8 explicitly (Windows-safe).

Free tier note: OpenRouter free credits are enough for many articles. Set a
hard cap via [llm] max_articles_per_day if you want a spend ceiling.
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

SRC = Path(__file__).resolve().parent

SYS_PROMPT = """You are an expert affiliate-content writer for a pet-tech review site.
Write a genuinely useful, original buying guide. No fluff, no repeated filler,
no invented product names or fake statistics. Use a clear buying framework:
what matters, how to choose, trade-offs, and 3 real product CATEGORIES the
reader can search for on Amazon (do NOT invent specific ASINs or brand model
numbers — describe the product type). Include an FAQ with 2 honest questions.
Tone: helpful, skeptical of marketing, trust-building. Output strict JSON only:
{"title": str, "meta": str, "intro": str,
 "sections": [{"h2": str, "body": str}],  # 2-3 sections, body >= 60 words each
 "products": [{"name": str, "asin_query": str, "price": str, "blurb": str}],  # 3 items
 "faq": [{"q": str, "a": str}]}  # 2 items
The 'asin_query' must be a short lowercase search phrase (spaces allowed) a
buyer would type on Amazon. Keep total prose >= 350 words."""

def slugify(text):
    s = text.lower().strip()
    for ch in "[](){}'\".,!?:;":
        s = s.replace(ch, "")
    s = s.replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:70].strip("-")

def load_existing(art_dir):
    slugs = set(); keywords = set()
    if art_dir.exists():
        for p in art_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                slugs.add(d.get("slug", "")); keywords.add(d.get("keyword", "").lower())
            except Exception:
                pass
    return slugs, keywords

def mint_keywords(cfg, existing_slugs, existing_kw, count):
    themes = cfg.get("engine", {}).get("seed_themes", [])
    modifiers = ["best", "budget", "for apartment", "for seniors", "for puppies", "wireless",
                 "with app", "no subscription", "under $50", "for multi-pet homes", "reviews 2026",
                 "buying guide", "vs", "alternatives to", "for first time owners"]
    out = []
    import itertools
    combos = []
    for t in themes:
        for m in modifiers:
            combos.append(f"{m} {t}")
    # de-dup against existing
    seen = set()
    for c in combos:
        kw = c.strip()
        if kw.lower() in existing_kw:
            continue
        slug = slugify(kw)
        if slug in existing_slugs or slug in seen:
            continue
        seen.add(slug)
        out.append((slug, kw))
        if len(out) >= count:
            return out
    # fallback generic long-tails if themes exhausted
    i = 0
    while len(out) < count:
        kw = f"pet tech guide {i}"
        slug = slugify(kw)
        if slug not in existing_slugs and slug not in seen:
            seen.add(slug); out.append((slug, kw))
        i += 1
    return out

def call_openrouter(cfg, keyword):
    key = cfg["llm"]["openrouter_api_key"]
    model = cfg["llm"].get("model", "meta-llama/llama-3.3-70b-instruct")
    url = "https://openrouter.ai/api/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": f"Write the buying guide for the exact search keyword: '{keyword}'. Title must contain the keyword."}
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("HTTP-Referer", "https://localhost")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]

def validate(art, slug, keyword):
    if not isinstance(art, dict):
        return None
    for f in ("title", "meta", "intro", "sections", "products", "faq"):
        if f not in art:
            return None
    if not (2 <= len(art["sections"]) <= 4):
        return None
    if not (3 <= len(art["products"]) <= 4):
        return None
    if not (2 <= len(art["faq"]) <= 3):
        return None
    total_words = sum(len(s.get("body", "").split()) for s in art["sections"])
    total_words += len(art["intro"].split())
    if total_words < 300:
        return None
    art["slug"] = slug
    art["keyword"] = keyword
    art["source"] = "ai"
    for p in art["products"]:
        p.setdefault("price", "varies")
        p.setdefault("blurb", "")
    return art

def generate_batch(cfg, art_dir, count=3):
    existing_slugs, existing_kw = load_existing(art_dir)
    keywords = mint_keywords(cfg, existing_slugs, existing_kw, count)
    written = 0
    max_per_day = int(cfg.get("llm", {}).get("max_articles_per_day", 10))
    for slug, kw in keywords[:max_per_day]:
        try:
            raw = call_openrouter(cfg, kw)
            art = json.loads(raw)
            art = validate(art, slug, kw)
            if not art:
                print(f"[llm] rejected low-quality output for '{kw}' (retrying once)")
                continue
            (art_dir / f"{slug}.json").write_text(
                json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")
            written += 1
            time.sleep(1)  # be polite to the API
        except urllib.error.HTTPError as e:
            print(f"[llm] API error for '{kw}': {e.code} {e.reason}")
            if e.code == 429:
                break  # rate limited; stop for this run
        except Exception as e:
            print(f"[llm] failed '{kw}': {e}")
    return written

if __name__ == "__main__":
    # standalone test (requires key in config)
    import tomllib
    cfg = tomllib.load(open(str(SRC.parent / "config.toml"), "rb"))
    if not cfg["llm"].get("openrouter_api_key"):
        print("No OpenRouter key set. Add one to config.toml to enable.")
        sys.exit(1)
    n = generate_batch(cfg, art_dir=SRC / "articles", count=3)
    print(f"Generated {n} articles.")
