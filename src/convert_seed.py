# -*- coding: utf-8 -*-
"""Convert the existing SEED_ARTICLES list into individual JSON files under
src/articles/ so the engine can merge seed + AI-generated content. Run once."""
import json, sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
from seed_content import SEED_ARTICLES

OUT = SRC / "articles"
OUT.mkdir(exist_ok=True)

for art in SEED_ARTICLES:
    # normalize: ensure 'source' field
    art = dict(art)
    art.setdefault("source", "seed")
    (OUT / f"{art['slug']}.json").write_text(
        json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8"
    )
print(f"Wrote {len(SEED_ARTICLES)} seed articles to {OUT}")
