# Autonomous Affiliate Engine — Smart Pet Gear Lab

An agent-run, set-and-monitor affiliate content site. The agent builds and
publishes SEO articles on a schedule; you watch traffic/earnings.

## What's automated
- Niche picked, site scaffolded, 10 real seed articles authored
- Daily engine publishes one new article, rebuilds the site, commits to git
- Sitemap, RSS feed, robots.txt generated automatically

## Your 3 one-time steps (the human-only parts)
1. **Amazon Associates**: sign up (free) at https://affiliate-program.amazon.com
   and paste your tracking ID into `config.toml` → `affiliate.amazon_tag`.
2. **Create the GitHub repo**: on github.com create a repo named **affiliate-site**.
   Then in this folder run:
   ```
   git init
   git branch -M main
   git remote add origin https://github.com/YOURUSERNAME/affiliate-site.git
   git add -A && git commit -m "init"
   git push -u origin main
   ```
3. **Enable GitHub Pages**: repo Settings → Pages → Source: `main` branch,
   `/ (root)` → set `base_url` in config.toml to the shown URL and rerun `engine.py build`.

## Run it
```
python src/engine.py build     # build site into ./public
python src/engine.py run       # publish next article + commit
python src/engine.py status    # see progress
```

## Make it truly hands-off (optional upgrade)
Add a free OpenRouter key to `config.toml` under `[llm]` and set
`enable_autonomous_writing = true`. Then the daily engine mints brand-new
long-tail articles on its own instead of cycling seed content.

## Set the daily schedule (the agent does this for you via a cron job)
The agent schedules `python src/engine.py run` to fire daily. You never touch it.
