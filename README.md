# yunoballizer

A personal CLI tool for automatically collecting content from Instagram,
YouTube Shorts, and TikTok.

## Core design: separating account discovery from downloads

Instagram requires login to view saved posts, while public profile timelines
are still accessible anonymously. Login is therefore used only to discover the
authors of posts you saved. Fetch stores no media or captions; anonymous account
crawling handles all downloads.

```
[manual, login]      yuno fetch     -> adds saved-post authors to accounts.txt
                                            |
[frequent, no login] yuno download  -> downloads accounts.txt + urls.txt across
                                        Instagram/YouTube/TikTok
                                            |
[manual, no login]   yuno expand    -> adds @mentions found in downloaded
                                        Instagram captions to accounts.txt
```

`yuno profile` builds a content profile from downloaded Instagram captions,
and `yuno curate` filters downloaded posts against it.

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
| `youtube/accounts.txt` | YouTube channels' Shorts tab | Not required |
| `tiktok/accounts.txt` | TikTok accounts (hashtags not supported) | Not required |
| `urls.txt` | Individual TikTok/YouTube URLs to download | Not required |

## Usage

```bash
yuno download            # No login required. Crawls accounts.txt + urls.txt (Instagram/YouTube/TikTok)
yuno download @nasa      # Harvest a single account across all three platforms instead of the configured lists
yuno download -l 5       # Cap harvest at 5 posts per account (default: 20)
yuno fetch                # Login required. Adds saved-post authors to Instagram accounts.txt; downloads nothing
yuno expand               # No login required. Adds @mentions from downloaded Instagram captions
yuno profile              # Build/refresh a content profile from downloaded Instagram captions
yuno curate               # Curate downloaded posts against the content profile
yuno all                  # download + curate (cron entry point)
```

For `fetch`, first log in to `instagram.com` in the browser selected with
`--browser` (Chrome by default). Fetch imports that existing browser session;
it does not ask for or store your Instagram password.

## cron setup (macOS/Linux)

```bash
crontab -e
```

```
0 */6 * * * /path/to/venv/bin/yuno all >> ~/.local/share/yunoballizer/logs/cron.log 2>&1
```

`fetch` is meant to be run manually every 1-2 weeks, not from cron.

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
