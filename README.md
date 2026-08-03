# yunoballizer

A personal CLI tool for automatically collecting content from Instagram,
YouTube Shorts, and TikTok.

## Core design: separating "fetch" / "expand" from "harvest"

As of 2026, Instagram requires login for hashtag search and saved posts
(profile timelines are still accessible anonymously). So login is used
**only rarely, to fetch hashtag/saved data and grow the account list**,
while **anonymous, no-login account crawling handles the actual day-to-day
volume**.

```
[manual, login]      yuno fetch     -> saved posts + hashtag search results
                                            |
[manual, no login]   yuno expand    -> grows accounts.txt from fetch's hashtag
                                        authors + caption mentions in already-
                                        downloaded posts (no extra requests)
                                            |
[frequent, no login] yuno download  -> crawls accounts.txt + urls.txt across
                                        Instagram/YouTube/TikTok
```

`yuno profile` (taste profile) and `yuno curate` (filtering) sit on top of
this: `profile` reads `fetch`'s saved-post captions, and `curate` reads
`download`'s output.

## Install

```bash
pip install -e .
# or, once published: pip install yunoballizer
```

Installing registers both the `yunoballizer` and `yuno` commands on PATH
(no manual alias needed).

To use Claude API-based curation:

```bash
pip install -e ".[curate]"
export ANTHROPIC_API_KEY=sk-ant-...
```

## First-time setup

```bash
yuno download   # on first run, config templates are auto-created under ~/.config/yunoballizer/
```

Fill in the files under `~/.config/yunoballizer/`:

| File | Purpose | Login |
|---|---|---|
| `instagram/accounts.txt` | Instagram accounts to crawl | Not required |
| `instagram/hashtags.txt` | Hashtags for `yuno fetch` (auto-expands accounts.txt via `yuno expand`) | **Required** (fetch only) |
| `youtube/accounts.txt` | YouTube channels' Shorts tab | Not required |
| `tiktok/accounts.txt` | TikTok accounts (hashtags not supported) | Not required |
| `urls.txt` | Individual TikTok/YouTube URLs to download | Not required |

## Usage

```bash
yuno download            # No login required. Crawls accounts.txt + urls.txt (Instagram/YouTube/TikTok)
yuno download @nasa      # Harvest a single account across all three platforms instead of the configured lists
yuno download -l 5       # Cap harvest at 5 posts per account (default: 20)
yuno fetch                # Login required. Fetches saved posts + hashtag search results (manual, every 1-2 weeks)
yuno expand               # No login required. Grows accounts.txt from fetch's hashtag authors + caption mentions
yuno profile              # Build/refresh taste profile from fetch's saved-post captions
yuno curate               # Curate download's output against the taste profile
yuno all                  # download + curate (cron entry point)
```

For `fetch`, set `export IG_USERNAME=your_username` (or you'll be prompted
for it). The first run will also prompt for your password interactively
(and a 2FA code if enabled), then cache a session so future runs don't ask
again.

## cron setup (macOS/Linux)

```bash
crontab -e
```

```
0 */6 * * * /path/to/venv/bin/yuno all >> ~/.local/share/yunoballizer/logs/cron.log 2>&1
```

`fetch`/`expand` are meant to be run manually every 1-2 weeks, not from cron.

## Data locations

- Config: `~/.config/yunoballizer/`
- Collected data: `~/.local/share/yunoballizer/sources/`
- Logs: `~/.local/share/yunoballizer/logs/`

## Uninstalling

```bash
yuno prune
```

This removes the config, data, and log directories this app created
(`~/.config/yunoballizer/` and `~/.local/share/yunoballizer/`), after asking
for confirmation (use `-y`/`--yes` to skip the prompt). It does **not**
remove the installed Python package itself — for that, run:

```bash
pip uninstall yunoballizer
```

## Notes

- TikTok hashtag/trending discovery isn't supported at all right now — the
  yt-dlp extractor for it is broken upstream, independent of login.
- Even anonymous harvesting can trigger a temporary IP-level block if run
  too aggressively.
- Instagram's Terms of Service explicitly prohibit automated collection.
  Anonymous harvesting only removes the risk of your account being flagged
  — it doesn't make the activity ToS-compliant.
- Saving/repurposing other people's content may raise copyright concerns.
  Use this for personal reference/archiving only, and double-check before
  redistributing anything.
