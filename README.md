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
yuno download   # on first run, config templates are auto-created under $CONFIG_ROOT (see below)
```

Fill in the account list files:

| File | Purpose | Login |
|---|---|---|
| `instagram/accounts.txt` | Instagram accounts to crawl | Not required |
| `youtube/accounts.txt` | YouTube accounts' Shorts tab | Not required |
| `tiktok/accounts.txt` | TikTok accounts (hashtags not supported) | Not required |
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
yuno select                # Mark favorites in review/ with an image viewer (default: nsxiv)
yuno select --viewer "sxiv -o -t"  # Use a different viewer command
yuno export                # Copy/hardlink everything you've selected into selected/
yuno all                  # download + curate (cron entry point)
```

`-s`/`--skip` and `-l`/`--limit` mean the same thing across all three
platforms: skip the N most recent posts per account, then harvest the next L.

For `fetch`, first log in to `instagram.com` in the browser selected with
`--browser` (Chrome by default). Fetch imports that existing browser session;
it does not ask for or store your Instagram password.

## cron setup (macOS/Linux)

```bash
crontab -e
```

```
0 */6 * * * /path/to/venv/bin/yuno all >> ~/.local/state/yunoballizer/logs/cron.log 2>&1
```

`fetch` is meant to be run manually every 1-2 weeks, not from cron.

## Data locations

yunoballizer follows the XDG Base Directory conventions instead of any
macOS-specific location, since it's a cross-platform CLI, not a macOS app.
It never redirects to `~/Library/Application Support` just because you're on
macOS -- if you want data in a Finder-visible spot or on an external disk,
point `YUNOBALLIZER_DATA_DIR` at it directly.

| Kind | Priority order |
|---|---|
| Data | `$YUNOBALLIZER_DATA_DIR`, then `$XDG_DATA_HOME/yunoballizer`, then `~/.local/share/yunoballizer` |
| Config | `$XDG_CONFIG_HOME/yunoballizer`, then `~/.config/yunoballizer` |
| State | `$XDG_STATE_HOME/yunoballizer`, then `~/.local/state/yunoballizer` |

A relative path in any of these environment variables is rejected with an
error at startup rather than silently falling back, so a typo can't quietly
redirect where your content ends up.

Using the defaults, the layout looks like this:

```
~/.local/share/yunoballizer/
├── sources/
│   ├── instagram/<account>/<post-id>/
│   │   ├── image_01.jpg
│   │   ├── image_02.jpg
│   │   ├── video.mp4
│   │   ├── caption.txt
│   │   └── metadata.json.xz
│   ├── youtube/<account>/<video-id>/
│   ├── tiktok/<account>/<post-id>/
│   └── other/<extractor>/<uploader>/<post-id>/
├── review/               # flat symlinks into sources/, for browsing
├── curated/              # copies of posts `yuno curate` decided to keep
├── selected/             # real files (hardlinked/copied) for posts you picked with `yuno select`
└── derived/
    └── taste_profile.json

~/.local/state/yunoballizer/
├── archives/             # yt-dlp download-archive files (dedup)
├── curation_log.json
├── selection_log.json
└── logs/

~/.config/yunoballizer/
├── instagram/accounts.txt
├── youtube/accounts.txt
├── tiktok/accounts.txt
└── urls.txt
```

**`sources/`** is the source of truth. Every downloaded post is a single
self-contained directory holding its media, caption, and metadata together --
deleting, moving, or backing up a post is one directory, not a scattered set
of files. Instagram carousels keep every image/video from the post in that
same directory, numbered by stable sequence (`image_01`, `image_02`, ...).
Post directories are named by the platform's own stable ID (Instagram
shortcode; YouTube/TikTok/yt-dlp video ID) where available.

**`review/`** is just a regenerated index, not a second copy of your data: a
flat directory of symlinks into `sources/`, so you can browse everything at a
glance instead of digging through nested account folders. Link names encode
platform/account/post-id/media for readability, plus a short hash of the
source path so names never collide -- but the symlink target, not the
filename, is the source of truth; nothing parses link names back into
metadata. Deleting a link never touches the original file, and deleting
`review/` entirely is safe -- `yuno download` regenerates it from `sources/`
every run. Profile pictures are never downloaded in the first place, so they
never show up here either. If you want an automatically curated subset, use
`yuno curate`, which copies posts it keeps into `curated/`.

**`yuno select`** is for manually picking favorites instead of relying on
automatic curation. It launches an external image viewer's mark mode (nsxiv
by default -- `-o -t` for thumbnail-grid mode that prints marked files to
stdout on quit) over `review/`, then records whatever you marked into
`selection_log.json` as a plain manifest. review/'s symlinks are still just a
disposable browsing index, so selection state deliberately lives outside the
filesystem instead of being encoded via symlinks -- nothing about marking a
file changes `review/` or `sources/`. Run `yuno export` afterwards to
materialize the manifest into `selected/`: real files (hardlinked when
`selected/` shares a filesystem with `sources/`, copied otherwise), not
symlinks, so `selected/` works with any downstream tool, sync client, or
mobile app without special-casing links. `nsxiv` is an optional runtime
dependency invoked as a subprocess -- install it separately (`nsxiv` is
GPL-2, but yunoballizer only shells out to it rather than linking against
it, so that doesn't affect this project's own license), or point `--viewer`
at any command that prints marked file paths to stdout on exit.

## Uninstalling

```bash
yuno prune
```

This removes the config, data, and state directories this app created,
after asking for confirmation (use `-y`/`--yes` to skip the prompt). It does
**not** remove the installed Python package itself -- for that, run:

```bash
pip uninstall yunoballizer
```

## Notes

- TikTok hashtag/trending discovery isn't supported at all right now -- the
  yt-dlp extractor for it is broken upstream, independent of login.
- Even anonymous harvesting can trigger a temporary IP-level block if run
  too aggressively.
- Instagram's Terms of Service explicitly prohibit automated collection.
  Anonymous harvesting only removes the risk of your account being flagged
  -- it doesn't make the activity ToS-compliant.
- Saving/repurposing other people's content may raise copyright concerns.
  Use this for personal reference/archiving only, and double-check before
  redistributing anything.
