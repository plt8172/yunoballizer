# yunoballizer

A personal CLI tool for automatically collecting content from Instagram,
YouTube Shorts, and TikTok.

## Core design: separating "discovery" from "harvest"

As of 2026, Instagram requires login for hashtag/location search (profile
posts are still accessible anonymously). So login is used **only rarely, to
discover new accounts**, while **anonymous, no-login account crawling handles
the actual day-to-day volume**.

```
[occasional, login]  yunoballizer discover  -> hashtag search + saved posts -> discovers new accounts -> auto-added to accounts.txt
                                                                                    |
[daily, anonymous]   yunoballizer download  -> crawls accounts.txt for new posts
                                                + discovers more accounts from @mentions in captions (no extra requests)
                                                + also harvests YouTube Shorts / TikTok accounts / URL list
```

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
| `accounts.txt` | Instagram accounts' new posts/reels | Not required |
| `hashtags.txt` | Instagram hashtags -> account auto-discovery | **Required** |
| `youtube_channels.txt` | YouTube channels' Shorts tab | Not required |
| `youtube_hashtags.txt` | YouTube hashtags | Not required |
| `tiktok_accounts.txt` | TikTok accounts (hashtags not supported) | Not required |
| `urls.txt` | Individual TikTok/YouTube URLs to download | Not required |

## Usage

```bash
yuno download            # No login required. Crawls accounts.txt + urls.txt (Instagram/YouTube/TikTok)
yuno download @nasa      # Harvest a single account across all three platforms instead of the configured lists
yuno download -l 5       # Cap harvest at 5 posts per account (default: 20)
yuno download -s 5 -l 10 # Skip the newest 5 posts, then harvest the next 10 per account
yuno fetch                # Login required. Adds saved-post authors to Instagram accounts.txt; downloads nothing
yuno expand               # No login required. Adds @mentions from downloaded Instagram captions
yuno profile              # Build/refresh a content profile from downloaded Instagram captions
yuno curate               # Curate downloaded posts against the content profile
yuno all                  # download + curate (cron entry point)
```

For `discover`, log in once with `instaloader --login=your_username` to
create a session, then `export IG_USERNAME=your_username` before running it.

## cron setup (macOS/Linux)

```bash
crontab -e
```

```
0 */6 * * * IG_USERNAME=your_username /path/to/venv/bin/yuno all >> ~/.local/share/yunoballizer/logs/cron.log 2>&1
```

## Data locations

- Config: `~/.config/yunoballizer/`
- Collected data: `~/.local/share/yunoballizer/sources/`
- Logs: `~/.local/share/yunoballizer/logs/`

## Uninstalling

```bash
yuno uninstall
```

This removes the config, data, and log directories this app created
(`~/.config/yunoballizer/` and `~/.local/share/yunoballizer/`), after asking
for confirmation (use `-y`/`--yes` to skip the prompt). It does **not**
remove the installed Python package itself — for that, run:

```bash
pip uninstall yunoballizer
```

## Notes

- TikTok hashtag/trending discovery is not supported (accounts only).
- Even anonymous harvesting can trigger a temporary IP-level block if run
  too aggressively.
- Instagram's Terms of Service explicitly prohibit automated collection.
  Anonymous harvesting only removes the risk of your account being flagged
  — it doesn't make the activity ToS-compliant.
- Saving/repurposing other people's content may raise copyright concerns.
  Use this for personal reference/archiving only, and double-check before
  redistributing anything.
