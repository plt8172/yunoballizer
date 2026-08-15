# yunoballizer

A personal CLI tool for automatically collecting content from Instagram,
YouTube Shorts, and TikTok.

## Core design: separating account discovery from downloads

Instagram requires login to view saved posts, while public profile timelines
are still accessible anonymously. Login is therefore used only to discover the
authors of posts you saved. Fetch stores no media or captions; anonymous account
crawling handles all downloads.

```
[once/switch]         yuno auth login -> imports & saves an Instagram session
                                              |
[manual, uses saved   yuno fetch      -> adds saved-post authors to accounts.txt
 session]                                    |
[frequent, no login]  yuno download   -> downloads accounts.txt + urls.txt across
                                         Instagram/YouTube/TikTok
                                              |
[manual, no login]    yuno expand     -> adds @mentions found in downloaded
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
yuno fetch                # Uses the active saved session. Adds saved-post authors to Instagram accounts.txt; downloads nothing
yuno expand               # No login required. Adds @mentions from downloaded Instagram captions
yuno profile              # Build/refresh a content profile from downloaded Instagram captions
yuno curate               # Curate downloaded posts against the content profile
yuno all                  # download + curate (cron entry point)

yuno auth login               # Open a login window driving Chrome (default); falls back to cookie import if that fails
yuno auth login -b edge       # Same, driving Edge instead
yuno auth login -b firefox    # Not chrome/edge: skips the login window, imports cookies from that browser instead
yuno auth login -y            # Skip the confirmation prompt (e.g. for scripted use)
yuno auth status              # List saved sessions, marking the active one with *
yuno auth status -c           # Also verify each saved session is still logged in (slower: one request per session)
yuno auth switch <user>       # Switch which saved session `fetch` uses, without touching the browser
yuno auth switch              # No user given: cycle to the next saved session (like `gh auth switch`)
yuno auth logout [<user>...]  # Remove one or more saved sessions (defaults to just the active one)
```

`-s`/`--skip` and `-l`/`--limit` mean the same thing across all three
platforms: skip the N most recent posts per account, then harvest the next L.

### Instagram login (`yuno auth`)

Instagram login is still cookie-based -- there's no practical way around
that. `yuno auth login` defaults to opening a separate, disposable browser
window and waiting for you to log in inside it, driving your already
installed Chrome (or `-b edge` for Edge) directly -- no extra download, and
your everyday browser's own session is never touched. This is the better
way to add another account: no logging your everyday browser out of one
account and into another.

If that isn't possible -- `-b` names some other browser, or the login
window fails to launch for any reason (not installed, closed before you
finished, etc.) -- `auth login` automatically falls back to importing
the session already active in that browser instead, telling you why before
it does. That fallback does require logging in to `instagram.com` in that
browser yourself first.

Either way, it never asks for or stores your Instagram password -- only
the session cookies Instagram itself issues after you log in.

Login is not silent: cookie import can only ever see one account at a time
(the one currently active in the browser, or the one you just logged into
in the login window), so `auth login` always shows you the detected
username and asks for confirmation before saving it -- the closest thing to
an account picker that cookie-based auth allows. Pass `-y`/`--yes` to skip
that prompt.

Saved sessions are kept on disk (like `gh auth`) as cookie data, functionally
equivalent to a logged-in session for that account -- `auth login` writes
each session file (and the sessions directory, and the active-session
marker) with `0600`/`0700` permissions so only your user account can read
them. Deleting `instagram/sessions/` (or running `yuno auth logout`) revokes
them locally at any time; it doesn't affect the browser or Instagram itself.
Since Instagram can expire or revoke a session independently of anything
this tool does, run `yuno auth status -c` occasionally to check whether a
saved session still works before `fetch` runs into it.

`fetch` doesn't need the browser on every run, and you can juggle multiple
Instagram accounts:

```bash
yuno auth login                # log in as account A in the login window; saved and made active
yuno auth login                # log in as account B in a fresh login window; B becomes active
yuno auth status                #   * account-b
                                 #     account-a
yuno auth switch account-a      # make A active again, no browser needed
yuno fetch                      # runs against whichever account is active
```

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
└── derived/
    └── taste_profile.json

~/.local/state/yunoballizer/
├── archives/             # yt-dlp download-archive files (dedup)
├── curation_log.json
└── logs/

~/.config/yunoballizer/
├── instagram/
│   ├── accounts.txt
│   ├── active_session       # username of the session `fetch` currently uses
│   └── sessions/            # one file per `yuno auth login`, named <username>.session
├── youtube/accounts.txt
├── tiktok/accounts.txt
└── urls.txt
```

Session files hold cookies, not your password, and are written `0600`
(the containing `sessions/` directory `0700`) -- see [Instagram
login](#instagram-login-yuno-auth) above for details.

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
never show up here either. There's no selected/rejected/pending split; if you
want a curated subset, use `yuno curate`, which copies posts it keeps into
`curated/`.

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
