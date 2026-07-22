#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTONOMOUS AFFILIATE ENGINE
===========================
Builds a GitHub-Pages-ready affiliate site from curated seed content and
runs on a schedule to publish new articles.

Commands:
  python engine.py build            # (re)build the whole site into ./public
  python engine.py run              # daily engine: publish next article, build, commit
  python engine.py status           # show what's published + next keyword

Only dependency: Python 3.11+ (uses stdlib tomllib). No pip installs needed.
"""
import os
import sys
import json
import html
import subprocess
from pathlib import Path
from datetime import datetime, timezone

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PUBLIC = ROOT / "public"
CONFIG_PATH = ROOT / "config.toml"
STATE_PATH = ROOT / "state.json"

# ---------------------------------------------------------------- config
def load_config():
    if tomllib is None:
        # minimal fallback parser
        cfg = {"site": {}, "affiliate": {}, "llm": {}, "publish": {}, "engine": {}}
        return cfg
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
        return json.loads(STATE_PATH.read_text())
    return {"published": [], "queue_index": 0, "history": []}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

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

# ---------------------------------------------------------------- render
def render_article(cfg, art):
    title = esc(art["title"])
    meta = esc(art.get("meta", ""))
    intro = esc(art.get("intro", ""))
    site_title = esc(get(cfg, "site", "title", default="Affiliate Site"))
    base = esc(get(cfg, "site", "base_url", default=""))

    parts = [f'<p class="intro">{intro}</p>']
    for sec in art.get("sections", []):
        parts.append(f'<h2>{esc(sec["h2"])}</h2>')
        parts.append(f'<p>{esc(sec["body"])}</p>')
    sections_html = "\n".join(parts)

    # product cards
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
        items = "".join(f"<dt>{esc(q)}</dt><dd>{esc(a)}</dd>" for q, a in [(f['q'], f['a']) for f in faq])
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
<p class="disclaimer">As an Amazon Associate we earn from qualifying purchases. Prices shown are approximate and change often.</p>
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
    feed = esc(f"{base}/feed.xml")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site_title}</title>
<meta name="description" content="{desc}">
<link rel="alternate" type="application/rss+xml" title="{site_title}" href="feed.xml">
<style>{CSS}</style>
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
    urls = "\n".join(urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
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
    items = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{site_title}</title>
  <link>{base}/</link>
  <description>{esc(get(cfg,'site','description',default=''))}</description>
{items}
</channel>
</rss>"""

CSS = """
:root{--bg:#0f1115;--card:#181b22;--fg:#e8e8ea;--muted:#9aa0aa;--accent:#5b8cff;--border:#262b34}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{background:var(--card);padding:14px 20px;border-bottom:1px solid var(--border)}
.brand{color:var(--accent);font-weight:700;font-size:18px;text-decoration:none}
main{max-width:820px;margin:0 auto;padding:28px 20px}
.article h1,.index+h2{font-size:30px;line-height:1.25}
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

# ---------------------------------------------------------------- build
def build(cfg, articles):
    PUBLIC.mkdir(exist_ok=True)
    published = [a for a in articles if a["slug"] in load_state().get("published", [])]
    # include all known articles for index/sitemap
    all_arts = articles
    (PUBLIC / "index.html").write_text(render_index(cfg, all_arts), encoding="utf-8")
    for a in all_arts:
        (PUBLIC / f"{a['slug']}.html").write_text(render_article(cfg, a), encoding="utf-8")
    (PUBLIC / "sitemap.xml").write_text(render_sitemap(cfg, all_arts), encoding="utf-8")
    (PUBLIC / "feed.xml").write_text(render_feed(cfg, all_arts), encoding="utf-8")
    (PUBLIC / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: " +
        get(cfg, "site", "base_url", default="https://example.com").rstrip("/") + "/sitemap.xml\n")
    # GitHub Pages needs this to serve from project root
    (PUBLIC / ".nojekyll").write_text("", encoding="utf-8")
    n_pub = len(set(a["slug"] for a in all_arts))
    return n_pub

# ---------------------------------------------------------------- daily run
def run(cfg):
    try:
        from seed_content import SEED_ARTICLES
    except ImportError:
        sys.path.insert(0, str(SRC))
        from seed_content import SEED_ARTICLES
    state = load_state()
    published = set(state.get("published", []))
    queue = [a for a in SEED_ARTICLES if a["slug"] not in published]
    if not queue:
        msg = "Queue empty — all seed articles published. Add more seed content or enable autonomous LLM writing."
        print(msg)
        return msg
    # pick next by queue order (round-robin)
    art = queue[0]
    published.add(art["slug"])
    state["published"] = list(published)
    state["history"].append({"slug": art["slug"], "keyword": art["keyword"], "date": now_iso()})
    save_state(state)
    n = build(cfg, SEED_ARTICLES)
    # git commit + optional push (push needs a remote + credentials = your setup)
    if get(cfg, "publish", "auto_git_commit", default=True):
        try:
            subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(ROOT), "commit", "-m",
                            f"publish: {art['keyword']} ({now_iso()})"], check=True, capture_output=True)
            print(f"[git] committed new article: {art['slug']}")
        except subprocess.CalledProcessError as e:
            print(f"[git] commit skipped/failed (repo not initialized yet?): {e}")
        if get(cfg, "publish", "auto_git_push", default=False):
            try:
                subprocess.run(["git", "-C", str(ROOT), "push"], check=True, capture_output=True)
                print("[git] pushed to remote -> GitHub Pages will rebuild")
            except subprocess.CalledProcessError as e:
                print(f"[git] push skipped/failed (need remote + token?): {e}")
    print(f"[ok] published '{art['keyword']}' | total articles: {n} | remaining in queue: {len(queue)-1}")
    return art["slug"]

def status(cfg):
    try:
        from seed_content import SEED_ARTICLES
    except ImportError:
        sys.path.insert(0, str(SRC))
        from seed_content import SEED_ARTICLES
    state = load_state()
    published = state.get("published", [])
    queue = [a for a in SEED_ARTICLES if a["slug"] not in published]
    print(f"Total seed articles: {len(SEED_ARTICLES)}")
    print(f"Published: {len(published)} -> {published}")
    print(f"Next to publish: {queue[0]['keyword'] if queue else 'NONE (queue empty)'}")
    print(f"Auto-git-commit: {get(cfg,'publish','auto_git_commit',default=True)}")
    print(f"Amazon tag set: {get(cfg,'affiliate','amazon_tag') != 'YOURTAG-20'}")
    return state

# ---------------------------------------------------------------- main
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    cfg = load_config()
    if cmd == "build":
        try:
            from seed_content import SEED_ARTICLES
        except ImportError:
            sys.path.insert(0, str(SRC))
            from seed_content import SEED_ARTICLES
        n = build(cfg, SEED_ARTICLES)
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
