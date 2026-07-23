#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTONOMOUS AFFILIATE ENGINE
===========================
Builds a GitHub-Pages-ready affiliate site from article JSON files in
src/articles/ and runs on a schedule to publish new articles.

Commands:
  python engine.py build            # (re)build the whole site into ./public
  python engine.py run              # daily engine: publish N queued articles, build, commit, push
  python engine.py status           # show what's published + next keyword

Behavior:
  - Reads every *.json in src/articles/ (seed + AI-generated merged together).
  - Publishes up to `articles_per_run` queued articles per run.
  - If autonomous writing is enabled AND the queue is empty, mints new
    long-tail articles via the LLM writer before publishing.

Only dependency: Python 3.11+ (stdlib tomllib). No pip installs needed.
"""
import os
import sys
import json
import html
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ART_DIR = SRC / "articles"
PUBLIC = ROOT / "public"
CONFIG_PATH = ROOT / "config.toml"
STATE_PATH = ROOT / "state.json"

# ---------------------------------------------------------------- config
def load_config():
    if tomllib is None:
        return {"site": {}, "affiliate": {}, "llm": {}, "publish": {}, "engine": {}}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)

def get(cfg, *keys, default=""):
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

# ---------------------------------------------------------------- state
def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"published": [], "queue_index": 0, "history": [], "generated": []}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------- articles
def load_articles():
    arts = []
    if ART_DIR.exists():
        for p in sorted(ART_DIR.glob("*.json")):
            try:
                arts.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception as e:
                print(f"[warn] skip bad article {p.name}: {e}")
    return arts

# ---------------------------------------------------------------- helpers
def aff_link(cfg, query):
    base = get(cfg, "affiliate", "amazon_search_url", default="https://www.amazon.com/s?k=")
    tag = get(cfg, "affiliate", "amazon_tag", default="YOURTAG-20")
    q = query.replace(" ", "+")
    return f"{base}{q}&tag={tag}"

def esc(s):
    return html.escape(str(s))

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def write(path, text):
    path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------- render
CSS = """
:root{--bg:#0f1115;--card:#181b22;--fg:#e8e8ea;--muted:#9aa0aa;--accent:#5b8cff;--border:#262b34}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{background:var(--card);padding:14px 20px;border-bottom:1px solid var(--border)}
.brand{color:var(--accent);font-weight:700;font-size:18px;text-decoration:none}
main{max-width:820px;margin:0 auto;padding:28px 20px}
.article h1{font-size:30px;line-height:1.25}
.meta,.k{color:var(--muted);font-size:14px}
.lead{color:var(--muted);font-size:18px}
h2{margin-top:34px;border-bottom:1px solid var(--border);padding-bottom:6px}
.intro{font-size:18px}
.cards{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));margin-top:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
.card h3{margin:0 0 6px;font-size:16px}
.card h3 a{color:var(--fg);text-decoration:none}
.price{color:var(--accent);font-weight:600;margin:4px 0}
.btn{display:inline-block;margin-top:8px;background:var(--accent);color:#fff;padding:8px 12px;border-radius:8px;text-decoration:none;font-size:14px}
ul.index{list-style:none;padding:0}
ul.index li{padding:12px 0;border-bottom:1px solid var(--border)}
ul.index a{color:var(--fg);font-size:18px;text-decoration:none;font-weight:600}
ul.index a:hover{color:var(--accent)}
.faq dt{font-weight:600;margin-top:10px}
.faq dd{margin:0;color:var(--muted)}
.disclaimer{font-size:13px;color:var(--muted);border-top:1px solid var(--border);margin-top:30px;padding-top:14px}
.back a{color:var(--accent);text-decoration:none}
footer{padding:20px;text-align:center;color:var(--muted);font-size:13px;border-top:1px solid var(--border)}
"""

def analytics_tag(cfg):
    """Return analytics <script> snippet, or '' if not configured.
    Supports Plausible (plausible.io) or Cloudflare Web Analytics.
    Privacy-friendly (no cookies), safe for a static affiliate site."""
    prov = get(cfg, "analytics", "provider", default="").lower().strip()
    if prov == "plausible":
        pid = get(cfg, "analytics", "plausible_domain", default="")
        if not pid:
            return ""
        return (f'<script defer data-domain="{esc(pid)}" '
                f'src="https://plausible.io/js/script.js"></script>')
    if prov == "cloudflare":
        tid = get(cfg, "analytics", "cloudflare_token", default="")
        if not tid:
            return ""
        return (f'<script defer src="https://static.cloudflareinsights.com/'
                f'beacon.min.js" data-cf-beacon=\'{{"token": "{esc(tid)}"}}\'></script>')
    return ""

def render_article(cfg, art):
    title = esc(art["title"]); meta = esc(art.get("meta", "")); intro = esc(art.get("intro", ""))
    site_title = esc(get(cfg, "site", "title", default="Affiliate Site"))
    base = esc(get(cfg, "site", "base_url", default=""))
    parts = [f'<p class="intro">{intro}</p>']
    for sec in art.get("sections", []):
        parts.append(f'<h2>{esc(sec["h2"])}</h2>')
        parts.append(f'<p>{esc(sec["body"])}</p>')
    sections_html = "\n".join(parts)
    cards = []
    for p in art.get("products", []):
        link = aff_link(cfg, p["asin_query"])
        cards.append(f"""
        <div class="card">
          <h3><a href="{link}" target="_blank" rel="sponsored noopener">{esc(p['name'])}</a></h3>
          <p class="price">{esc(p.get('price',''))}</p>
          <p>{esc(p.get('blurb',''))}</p>
          <a class="btn" href="{link}" target="_blank" rel="sponsored noopener">Check price on Amazon &rarr;</a>
        </div>""")
    products_html = "\n".join(cards)
    faq = art.get("faq", [])
    faq_html = ""
    if faq:
        items = "".join(f"<dt>{esc(f['q'])}</dt><dd>{esc(f['a'])}</dd>" for f in faq)
        faq_html = f'<h2>Frequently Asked Questions</h2><dl class="faq">{items}</dl>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | {site_title}</title>
<meta name="description" content="{meta}">
<link rel="canonical" href="{base}/{art['slug']}.html">
<style>{CSS}</style>
{analytics_tag(cfg)}
</head>
<body>
<header><a class="brand" href="index.html">{site_title}</a></header>
<main class="article">
<h1>{title}</h1>
<p class="meta">{meta}</p>
{sections_html}
<h2>Top Picks</h2>
<div class="cards">{products_html}</div>
{faq_html}
<p class="disclaimer">As an Amazon Associate we earn from qualifying purchases. Prices shown are approximate and change often. This site contains affiliate links; we may earn a commission at no extra cost to you.</p>
<p class="back"><a href="index.html">&larr; Back to all guides</a></p>
</main>
<footer><p>&copy; {datetime.now().year} {site_title}. Affiliate disclosure: links may earn us a commission at no extra cost to you.</p></footer>
</body>
</html>"""

def render_index(cfg, articles):
    site_title = esc(get(cfg, "site", "title", default="Affiliate Site"))
    tagline = esc(get(cfg, "site", "tagline", default=""))
    desc = esc(get(cfg, "site", "description", default=""))
    base = esc(get(cfg, "site", "base_url", default=""))
    items = []
    for a in articles:
        items.append(f'<li><a href="{a["slug"]}.html">{esc(a["title"])}</a><br><span class="k">{esc(a.get("keyword",""))}</span></li>')
    list_html = "\n".join(items)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site_title}</title>
<meta name="description" content="{desc}">
<link rel="alternate" type="application/rss+xml" title="{site_title}" href="feed.xml">
<style>{CSS}</style>
{analytics_tag(cfg)}
</head>
<body>
<header><span class="brand">{site_title}</span></header>
<main>
<h1>{tagline}</h1>
<p class="lead">{desc}</p>
<h2>Guides</h2>
<ul class="index">{list_html}</ul>
</main>
<footer><p>&copy; {datetime.now().year} {site_title}. Affiliate disclosure: links may earn us a commission at no extra cost to you.</p></footer>
</body>
</html>"""

def render_sitemap(cfg, articles):
    base = get(cfg, "site", "base_url", default="https://example.com").rstrip("/")
    urls = [f"  <url><loc>{base}/index.html</loc></url>"]
    for a in articles:
        urls.append(f"  <url><loc>{base}/{a['slug']}.html</loc></url>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

def render_feed(cfg, articles):
    site_title = esc(get(cfg, "site", "title", default="Affiliate Site"))
    base = get(cfg, "site", "base_url", default="https://example.com").rstrip("/")
    items = []
    for a in articles[:20]:
        link = f"{base}/{a['slug']}.html"
        items.append(f"""  <item>
    <title>{esc(a['title'])}</title>
    <link>{link}</link>
    <guid>{link}</guid>
    <description>{esc(a.get('meta',''))}</description>
  </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{site_title}</title>
  <link>{base}/</link>
  <description>{esc(get(cfg,'site','description',default=''))}</description>
{chr(10).join(items)}
</channel>
</rss>"""

# ---------------------------------------------------------------- IndexNow
# Free, instant, ban-safe discovery: tells search engines (Bing/Yandex/Naver,
# and Google via the Indexing API proxy) that new URLs exist so they index
# within HOURS instead of weeks. No account/ToS risk. Runs automatically on
# every publish. See https://www.indexnow.org/
import secrets as _secrets
def _indexnow_key():
    """Deterministic per-site key file (no external account needed).
    We generate it once and serve it at /<key>.txt ; the engine writes that
    file into public/ during build so the search engine can validate it."""
    key_file = ROOT / ".indexnow_key"
    if not key_file.exists():
        # 32-hex char key (IndexNow spec)
        key_file.write_text(_secrets.token_hex(16), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()

def ensure_indexnow_key_file(cfg):
    """Write the key verification file into public/ so IndexNow validates."""
    key = _indexnow_key()
    (PUBLIC / f"{key}.txt").write_text(key, encoding="utf-8")
    return key

def ping_indexnow(cfg, urls):
    """Ping search engines with newly published URLs. Best-effort; never
    raises (a network blip must not break publishing)."""
    if not urls:
        return
    key = _indexnow_key()
    host = get(cfg, "site", "base_url", default="").rstrip("/")
    if "://" in host:
        host = host.split("://", 1)[1]
    else:
        return
    payload = json.dumps({
        "host": host,
        "key": key,
        "urlList": urls,
        "keyLocation": f"https://{host}/{key}.txt",
    }).encode("utf-8")
    endpoints = [
        "https://api.indexnow.org/indexnow",
        "https://www.bing.com/indexnow",
    ]
    for ep in endpoints:
        try:
            req = urllib.request.Request(
                ep, data=payload, method="POST",
                headers={"Content-Type": "application/json; charset=utf-8"})
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.getcode()
            print(f"[indexnow] {ep.split('/')[2]}: {code}")
        except urllib.error.HTTPError as e:
            print(f"[indexnow] {ep.split('/')[2]}: HTTP {e.code}")
        except Exception as e:
            print(f"[indexnow] {ep.split('/')[2]}: {e}")

# ---------------------------------------------------------------- build
def build(cfg, articles):
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "index.html").write_text(render_index(cfg, articles), encoding="utf-8")
    for a in articles:
        (PUBLIC / f"{a['slug']}.html").write_text(render_article(cfg, a), encoding="utf-8")
    (PUBLIC / "sitemap.xml").write_text(render_sitemap(cfg, articles), encoding="utf-8")
    (PUBLIC / "feed.xml").write_text(render_feed(cfg, articles), encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: " +
        get(cfg, "site", "base_url", default="https://example.com").rstrip("/") + "/sitemap.xml\n",
        encoding="utf-8")
    (PUBLIC / ".nojekyll").write_text("", encoding="utf-8")
    ensure_indexnow_key_file(cfg)  # serve IndexNow key at /<key>.txt for validation
    return len(articles)

# ---------------------------------------------------------------- LLM hook
def maybe_generate(cfg, state, articles):
    """If autonomous writing is on and queue empty, mint new articles."""
    enabled = get(cfg, "llm", "enable_autonomous_writing", default=False)
    key = get(cfg, "llm", "openrouter_api_key", default="")
    if not (enabled and key):
        return 0
    try:
        sys.path.insert(0, str(SRC))
        from llm_writer import generate_batch
    except Exception as e:
        print(f"[llm] writer unavailable: {e}")
        return 0
    published = set(state.get("published", []))
    queue = [a for a in articles if a["slug"] not in published]
    if queue:
        return 0
    n = generate_batch(cfg, ART_DIR, count=max(3, get(cfg, "engine", "articles_per_run", default=1)))
    print(f"[llm] generated {n} new articles")
    return n

# ---------------------------------------------------------------- daily run
def run(cfg):
    articles = load_articles()
    state = load_state()
    published = set(state.get("published", []))
    # refill queue via LLM if enabled + empty
    maybe_generate(cfg, state, articles)
    articles = load_articles()  # reload after possible generation
    queue = [a for a in articles if a["slug"] not in published]
    per_run = int(get(cfg, "engine", "articles_per_run", default=1))
    batch = queue[:per_run]
    if not batch:
        print("Queue empty and autonomous writing off/ unavailable — nothing to publish.")
        return None
    for art in batch:
        published.add(art["slug"])
        state.setdefault("history", []).append(
            {"slug": art["slug"], "keyword": art["keyword"], "date": now_iso(),
             "source": art.get("source", "seed")})
    state["published"] = list(published)
    save_state(state)
    n = build(cfg, articles)
    _git_commit_push(cfg, batch)
    # Instant, ban-safe discovery: ping search engines with the NEW urls only.
    base = get(cfg, "site", "base_url", default="").rstrip("/")
    new_urls = [f"{base}/{a['slug']}.html" for a in batch]
    ping_indexnow(cfg, new_urls)
    print(f"[ok] published {len(batch)} article(s): " +
          ", ".join(a['keyword'] for a in batch) +
          f" | total: {n} | remaining: {len(queue)-len(batch)}")
    return [a["slug"] for a in batch]

def _git_commit_push(cfg, batch):
    if not get(cfg, "publish", "auto_git_commit", default=True):
        return
    try:
        subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True, capture_output=True)
        kw = "; ".join(a["keyword"] for a in batch)
        subprocess.run(["git", "-C", str(ROOT), "commit", "-m", f"publish: {kw} ({now_iso()})"],
                        check=True, capture_output=True)
        print("[git] committed")
    except subprocess.CalledProcessError as e:
        print(f"[git] commit skipped/failed: {e}")
    if get(cfg, "publish", "auto_git_push", default=False):
        try:
            subprocess.run(["git", "-C", str(ROOT), "push"], check=True, capture_output=True)
            print("[git] pushed -> Pages rebuilds")
        except subprocess.CalledProcessError as e:
            print(f"[git] push skipped/failed: {e}")

def status(cfg):
    articles = load_articles()
    state = load_state()
    published = state.get("published", [])
    queue = [a for a in articles if a["slug"] not in published]
    print(f"Total article files: {len(articles)}")
    print(f"Published: {len(published)}")
    print(f"Remaining in queue: {len(queue)}")
    print(f"Next: {queue[0]['keyword'] if queue else 'NONE (queue empty)'}")
    print(f"articles_per_run: {get(cfg,'engine','articles_per_run',default=1)}")
    print(f"Amazon tag set: {get(cfg,'affiliate','amazon_tag') != 'YOURTAG-20'}")
    print(f"Autonomous writing: {get(cfg,'llm','enable_autonomous_writing',default=False)}")
    return state

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    cfg = load_config()
    if cmd == "build":
        n = build(cfg, load_articles())
        print(f"[ok] built site with {n} articles into ./public")
    elif cmd == "run":
        run(cfg)
    elif cmd == "status":
        status(cfg)
    else:
        print("usage: engine.py [build|run|status]")
        sys.exit(1)

if __name__ == "__main__":
    main()
