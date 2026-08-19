# yunoballizer

A personal CLI tool for automatically collecting content from Instagram,
YouTube Shorts, and TikTok.

## Core design: separating account discovery from downloads

Instagram requires login to view saved posts, while public profile timelines
are still accessible anonymously. Login is therefore used only to discover the
authors of posts you saved. Fetch stores no media or captions; anonymous account
crawling handles all downloads.

```
[once/switch]         yuno auth login | imports & saves an Instagram session
                                      |
[manual, login]       yuno fetch      | adds saved-post authors to accounts.txt
                                      |
[frequent, no login]  yuno download   | downloads accounts.txt + urls.txt across
                                      | ig/yt and tiktok
[manual, no login]    yuno select     | a visual tool to select posts/videos manually
                                      |
[manual, no login]    yuno expand     | adds @mentions found in downloaded
                                      | captions to accounts.txt
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

`yuno curate`'s optional AI-assisted judgment (used when rule-based
scoring is ambiguous) uses the same LLM setup as `yuno larp` -- no extra
install, no separate key. Run `yuno brain config` once to set it up; see
the [`yuno brain`](#yuno-brain-ai-provider-profiles) section below.

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
yuno auth login               # Open a login window driving Chrome (default); falls back to cookie import if that fails
yuno auth login -b edge       # Same, driving Edge instead
yuno auth login -b firefox    # Not chrome/edge: skips the login window, imports cookies from that browser instead
yuno auth login -y            # Skip the confirmation prompt (e.g. for scripted use)
yuno auth status              # List saved sessions, marking the active one with *
yuno auth status -c           # Also verify each saved session is still logged in (slower: one request per session)
yuno auth switch <user>       # Switch which saved session `fetch` uses, without touching the browser
yuno auth switch              # No user given: cycle to the next saved session (like `gh auth switch`)
yuno auth logout [<user>...]  # Remove one or more saved sessions (defaults to just the active one)

yuno brain config groq   # Interactively save a named AI provider profile (API key hidden) and activate it
yuno brain               # Show the active profile
yuno brain list          # List saved profiles, marking the active one with *
yuno brain switch <name> # Switch which saved profile larp/curate use
yuno brain remove <name> # Delete a saved profile

yuno fetch                # Uses the active saved session. Adds saved-post authors to Instagram accounts.txt; downloads nothing

yuno download            # No login required. Crawls accounts.txt + urls.txt (Instagram/YouTube/TikTok)
yuno download @nasa      # Harvest a single account across all three platforms instead of the configured lists
yuno download -l 5       # Cap harvest at 5 posts per account (default: 20)
yuno download -s 5 -l 10 # Skip the newest 5 posts, then harvest the next 10 per account

yuno download -p instagram              # Only harvest Instagram (repeat -p for more than one platform)
yuno download --since 2026-01-01        # Only posts published on/after this date
yuno download --until 2026-06-30        # Only posts published on/before this date
yuno download -t photo                  # Only photos (YouTube Shorts/TikTok are always video, so this skips them)
yuno download --total-limit 50          # Cap posts requested across every account/platform combined
yuno download --delay 5                 # Seconds to wait between accounts (overrides each platform's own default)

yuno select                # Browse review/ one item at a time: s to select, c to save a larp template, o to open natively
yuno export                # Copy/hardlink everything you've selected into selected/

yuno expand               # No login required. Adds @mentions from downloaded Instagram captions
yuno profile              # Build/refresh a content profile from downloaded Instagram captions
yuno curate               # Curate downloaded posts against the content profile

yuno all                  # download + curate (cron entry point)

yuno larp --style casual  # Generate comment/caption text from a saved style's templates
```

`-s`/`--skip` and `-l`/`--limit` mean the same thing across all three
platforms: skip the N most recent posts per account, then harvest the next L.

### `yuno larp`: comment/caption text generation

`yuno larp` generates text for comments or captions in the style of your
own material. It sends your saved example templates as few-shot examples
to an LLM and asks it to write one new example in the same voice -- by
default a free-tier Llama model via [Groq](https://console.groq.com)'s
API, called over plain HTTPS with just the Python standard library (no
new required dependency), but you do need to run `yuno brain config`
once first -- see [`yuno brain`](#yuno-brain-ai-provider-profiles) below.

Templates are grouped into named styles (aliases) so different
voices/formats -- a chatty travel-caption style vs. a terse one-liner
style, say -- don't blend into an incoherent average. Each style is its
own file under `$CONFIG_DIR/larp/styles/<name>.txt` (blank-line-separated
template blocks, `#` for comments; editing it directly works too).

Templates get there two ways: the `add` subcommand below, or `yuno
select`'s `c` key, which files the item you're currently looking at --
its own downloaded caption, not something you type -- into a style you
pick. A separate action from `s` (picking favorites), not tied to whether
the current item is selected. The style prompt there tab-completes over
your existing styles (via `readline`, so not on Windows without
`pyreadline`) -- keep typing to create a new one instead.

```bash
yuno brain config   # first time only: save a free Groq key (https://console.groq.com/keys)

yuno larp add casual "오늘도 열심히 달렸다 #daily #run"   # save a template under the "casual" style
yuno larp list                                            # list saved styles and their template counts
yuno larp list casual                                     # browse "casual"'s saved templates one at a time (arrow keys)
yuno larp remove casual 0                                 # remove a template by index
yuno larp rename casual laid-back                         # rename a style (its alias)
yuno larp delete laid-back                                # delete a style and all its templates

yuno larp --style casual         # generate one text from the "casual" style
yuno larp --style casual -n 5    # generate 5
yuno larp --model llama-3.1-8b-instant   # faster, smaller model
yuno larp --style casual --language English   # keep the style, change the output language
yuno larp --max-tokens 1500   # give a reasoning/thinking model more room to finish
```

`--style` can be omitted if you only have one saved style (it's used
automatically); with two or more styles saved, `--style` is required so
styles never mix silently. Model: `--model`, then whatever's configured
(see below), then `llama-3.3-70b-versatile` as the built-in default.

`--max-tokens` caps how many output tokens a generation can use (default:
800). Some free models -- especially "reasoning"/"thinking" ones -- spend
part or all of that budget on hidden reasoning before producing visible
output; if `yuno larp` reports a model ran out of budget without
producing a response, raise `--max-tokens`, or switch to a plain
instruct/chat model instead.

`--language`/`-l` keeps the chosen style's voice and format but asks the
model to write the output in a different language than the saved
examples -- e.g. templates written in Korean, generated in English. Leave
it unset to just match whatever language the examples themselves are in.

Groq's free tier has rate limits (requests per minute/day); for occasional
personal use this comfortably fits, but if you hit one, `yuno larp` tells
you directly instead of failing silently.

### `yuno brain`: AI provider profiles

`yuno larp` and `yuno curate` share one AI provider setup, managed like
`yuno auth` manages Instagram sessions: save one or more named profiles,
switch between them, and whichever is active is what larp/curate use --
no CLI flags, no shell exports required.

```bash
yuno brain config groq        # save a profile named "groq" (API key hidden while typing) and activate it
yuno brain                    # show the active profile
yuno brain list                # list saved profiles, marking the active one with *
yuno brain switch <name>       # switch which saved profile is active
yuno brain remove <name>       # delete a saved profile
```

`yuno brain config <name>` prompts for an API key (via `getpass`, so it's
never echoed to the screen or left in shell history), then optionally a
model name and an API base URL -- leave either blank to use the built-in
default (Groq, `llama-3.3-70b-versatile`). Profiles are stored under
`$CONFIG_DIR/brain/profiles/<name>.json` with `0600` permissions (the
directory is `0700`), the same way `yuno auth` locks down saved Instagram
sessions.

Any provider that speaks the same OpenAI-compatible chat completions
format works, not just Groq -- OpenRouter, Together AI, Fireworks, a
local vLLM/LM Studio server, etc. Save each as its own named profile with
its own key/model/endpoint, then `yuno brain switch <name>` to change
which one larp/curate use:

```bash
yuno brain config openrouter
# API key for 'openrouter' (hidden, ...): sk-or-...
# Model [Enter for llama-3.3-70b-versatile]: meta-llama/llama-3.1-8b-instruct:free
# API base URL [Enter for https://api.groq.com/openai/v1/chat/completions]: https://openrouter.ai/api/v1/chat/completions

yuno brain switch groq   # back to the Groq profile
```

Providers with a genuinely different request format (not OpenAI-style
chat completions -- e.g. Anthropic's Messages API, Ollama's native
`/api/generate`) aren't supported this way.

Precedence, most to least specific: a CLI flag (`--model`/`--api-base` on
`yuno larp`) beats an environment variable (`YUNOBALLIZER_API_KEY`/
`YUNOBALLIZER_MODEL`/`YUNOBALLIZER_API_BASE`, whether `export`ed or
loaded from `$CONFIG_DIR/.env`) beats the active `yuno brain` profile
beats the built-in default. The `.env`/`export` route still works if you
prefer it (e.g. for scripted/non-interactive setup) -- `$CONFIG_DIR/.env`
is `KEY=value`, one per line, `#` comments, quotes around the value
optional, read once at startup:

```
# ~/.config/yunoballizer/.env
YUNOBALLIZER_API_KEY=gsk_...
YUNOBALLIZER_MODEL=llama-3.1-8b-instant
```

Either way, the key never leaves your machine except in the request
itself -- yunoballizer doesn't store or log it beyond the profile file
you asked it to save.

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
├── selected/             # real files (hardlinked/copied) for posts you picked with `yuno select`
└── derived/
    └── taste_profile.json

~/.local/state/yunoballizer/
├── archives/             # yt-dlp download-archive files (dedup)
├── curation_log.json
├── selection_log.json
└── logs/

~/.config/yunoballizer/
├── instagram/
│   ├── accounts.txt
│   ├── active_session       # username of the session `fetch` currently uses
│   └── sessions/            # one file per `yuno auth login`, named <username>.session
├── youtube/accounts.txt
├── tiktok/accounts.txt
├── urls.txt
├── larp/styles/
│   ├── casual.txt
│   └── formal.txt
├── brain/
│   ├── active_profile       # name of the profile larp/curate currently use
│   └── profiles/            # one file per `yuno brain config`, named <name>.json
└── .env                      # optional -- see `yuno brain`/`$CONFIG_DIR/.env` above
```

Session and brain-profile files hold cookies/keys, not your password, and
are written `0600` (their containing directories `0700`) -- see
[Instagram login](#instagram-login-yuno-auth) and [`yuno
brain`](#yuno-brain-ai-provider-profiles) above for details.

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
automatic curation. It shows one item from `review/` at a time -- account,
image, caption -- rather than a list-plus-preview split: `<-`/`->` move to
the previous/next item, `s` toggles it as selected, `o` opens it in your
OS's default viewer/player (for a closer look or if you need to play a
video), and Enter/`q` finishes the session. Whatever you selected gets
recorded into `selection_log.json` as a plain manifest. review/'s symlinks
are still just a disposable browsing index, so selection state deliberately
lives outside the filesystem instead of being encoded via symlinks --
nothing about selecting a file changes `review/` or `sources/`. Run
`yuno export` afterwards to materialize the manifest into `selected/`: real
files (hardlinked when `selected/` shares a filesystem with `sources/`,
copied otherwise), not symlinks, so `selected/` works with any downstream
tool, sync client, or mobile app without special-casing links.

`c` files the current item's own downloaded caption as a `yuno larp`
template: it prompts for which style to save it under (existing ones are
listed for reference), then appends the caption to that style's file, same
as `yuno larp add`. Nothing to type -- if the item has no caption there's
nothing to save. It's a completely separate action from `s` -- it never
touches `selection_log.json`, doesn't require the current item to be
selected, and selecting an item never writes a template.

One item at a time is a deliberate choice, not just simplicity for its own
sake: an earlier version used [fzf](https://github.com/junegunn/fzf) with a
live preview pane, but a navigable list and a concurrently-rendered image
fighting over the same terminal caused frequent, hard-to-avoid corruption
in practice (the list reads keystrokes from stdin while the image tool
queries the terminal for cursor position over that same stdin). Rendering
one full-width item at a time means only one process ever touches the
terminal, and it always finishes before the next keypress is read -- so
`yuno select` has no `fzf` dependency at all.

The picker previews each item with [`viu`](https://github.com/atanunq/viu)
-- videos show a single representative frame (extracted with `ffmpeg`, if
installed) rather than playing back in the terminal, since that turned out
to be the simplest thing that works identically across
macOS/Windows/Linux without heavier dependencies. `viu` is required for
`yuno select`; `ffmpeg` is optional (video previews just fall back to a
placeholder line without it). Both are invoked as subprocesses only, never
linked against, so their own licenses don't affect this project's.

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
