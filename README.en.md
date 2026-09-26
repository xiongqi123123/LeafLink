<p align="center">
  <img src="https://raw.githubusercontent.com/xiongqi123123/LeafLink/main/resource/leaflink.png" alt="LeafLink Logo" width="220" />
</p>

<h1 align="center">LeafLink</h1>

<p align="center">A CLI for syncing local folders with Overleaf and cn.overleaf projects</p>

<p align="center">
  <a href="https://pypi.org/project/leaflink/"><img src="https://img.shields.io/pypi/v/leaflink?label=PyPI&cacheSeconds=300" alt="PyPI" /></a>
<a href="https://pypi.org/project/leaflink/"><img src="https://img.shields.io/pypi/pyversions/leaflink?cacheSeconds=300" alt="Python" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/xiongqi123123/LeafLink/ci.yml?branch=main&label=CI" alt="CI" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink"><img src="https://img.shields.io/github/stars/xiongqi123123/LeafLink?style=flat" alt="GitHub stars" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink/blob/main/LICENSE.txt"><img src="https://img.shields.io/github/license/xiongqi123123/LeafLink" alt="License" /></a>
</p>

<p align="center">
  <a href="./README.md">简体中文</a> |
  <a href="https://github.com/xiongqi123123/LeafLink">GitHub</a> |
  <a href="https://pypi.org/project/leaflink/">PyPI</a>
</p>

<p align="center"><strong>Browser login, clone, pull, push, PDF download, and pseudo real-time sync in one tool.</strong></p>

## Overview

LeafLink is an open source command-line tool for synchronizing a local directory with an Overleaf project without relying on Overleaf's paid Git bridge.

It is inspired by the product shape of `overleaf-sync`, but it is not a fork. LeafLink is a clean-room rewrite built for:

- clearer architecture
- maintainable Python packaging
- browser-based authentication
- reliable local/remote state tracking
- easier testing and long-term extension

## Why Rewrite Instead of Fork

- To decouple authentication, client, sync engine, and CLI from the start
- To support both `overleaf.com` and `cn.overleaf.com` as first-class targets
- To add a `sync` command for local watch + remote polling collaboration
- To make the project easier to test, release, and maintain as a real PyPI package

## Highlights

- Browser login with persisted session cookies
- Cookie import (interactive prompt, `--cookie`, or JSON file) for servers without a browser
- List all accessible projects
- Clone by project URL, project ID, or exact project name
- Pull remote changes into a local working tree
- Push local changes to the remote project
- Download the latest compiled PDF
- Inspect local vs remote status without applying changes
- `sync` command for pseudo real-time collaboration
- Three-way text merge powered by `merge3`
- Binary-safe syncing for images, PDFs, archives, BibTeX files, style files, and more

## Supported URLs

- `https://www.overleaf.com/project/...`
- `https://cn.overleaf.com/project/...`


## Self-hosted Overleaf (0.3.0)

Use the origin of your instance, including its port when needed:

```bash
leaflink login --base-url https://overleaf.lan.example.com
leaflink list --base-url https://overleaf.lan.example.com
leaflink clone https://overleaf.lan.example.com/project/PROJECT_ID ./paper
```

Browser login or `leaflink auth import --base-url ...` (see
[Import cookies](#import-cookies-servers-without-a-browser)) can supply a session for that instance. Keep cookie files and `auth.json` out of
Git and workflow logs. Login sessions are scoped to their instance. Self-hosted
HTTP(S) origins are supported; reverse-proxy subpath deployments are not.
TLS certificate verification remains enabled. Editor API compatibility still
depends on the deployed Overleaf version; validate uploads on a test project first.

### Ignore behavior

Place `.leafignore` at the project root (or pass `--ignore-file` to the sync commands).
Rules filter **both local and remote** changes: clone/pull, push, and deletions.
Adding a rule leaves existing local and remote files untouched; it does not delete
them. The long-running sync loop reloads rules at the next synchronization check.
A first clone uses the remote ignore file if no local one exists; a pre-existing
local ignore file takes precedence. During pull, incoming rule changes are applied
before other files. If both sides edited the rule file, synchronization stops for
manual resolution instead of guessing which policy to use. Ignoring files does not avoid downloading the
project ZIP; filtering happens before files are applied locally.

Supported patterns: `*`, `?`, character classes, `**` for whole directory segments,
`/` for a root-anchored pattern, trailing `/` for directories, and `!` for re-inclusion.
Later matching rules win. For example:

```gitignore
build/
*.pdf
!figures/**
```

Unlike Git, LeafLink allows an explicit later rule to re-include a file beneath an
ignored directory. It reads one root ignore file; nested `.gitignore` files and Git's
backslash-escape syntax are not supported. `.git` and `.leaflink` metadata are always
excluded and cannot be re-included. `.leafignore` itself is synced unless excluded.
Default LaTeX artifact patterns still apply; ordinary rules may override them.

When running in disposable CI jobs, persist the project's `.leaflink` baseline
separately from authentication secrets. This release does not install a Gitea
workflow or automatically turn a new checkout into an initialized sync project.

## Installation

### Install from PyPI

```bash
pip install leaflink
```

Then run:

```bash
leaflink --help
```

### Install optional extras

```bash
pip install "leaflink[browser,watch]"
```

- `browser`: installs Playwright for browser login and remote discovery
- `watch`: installs `watchdog` for `leaflink sync`

### Install from source

```bash
git clone https://github.com/xiongqi123123/LeafLink.git
cd LeafLink
pip install .
```

### First-time Playwright setup

```bash
playwright install chromium
```

## Authentication

LeafLink stores reusable session data, not plaintext usernames or passwords.

Default config locations:

- `~/.config/leaflink/auth.json`
- `~/.config/leaflink/config.toml`

### Browser login

```bash
leaflink login
leaflink login --base-url https://cn.overleaf.com
```

Example output:

```text
[auth] Complete login in the browser window. leaflink will detect the session automatically and close the browser.
[ok] Saved session for https://cn.overleaf.com
```

### Import cookies (servers without a browser)

`leaflink login` needs a desktop browser. On an SSH server or container, log in with a
browser on any other machine, copy the session cookie, and import it on the server.

1. Log in to Overleaf, then open DevTools → Application (Firefox: Storage) → Cookies → your Overleaf site.
2. Copy the value of the session cookie:

   | Site | Cookie name |
   | --- | --- |
   | `www.overleaf.com` / `cn.overleaf.com` | `overleaf_session2` |
   | Self-hosted Overleaf (CE / Server Pro) | `sharelatex.sid` |

3. Import it in one of three ways.

**Interactive prompt (recommended)** — values are hidden and stay out of shell history:

```bash
leaflink auth import --base-url https://www.overleaf.com
```

```text
[auth] Enter cookies for https://www.overleaf.com from a logged-in browser (DevTools -> Application -> Cookies).
[auth] Session cookie: overleaf_session2 on overleaf.com, sharelatex.sid on self-hosted Overleaf.
[auth] Leave the name empty to finish.
Cookie name: overleaf_session2
Value of overleaf_session2 (hidden):
Cookie name:
[ok] Imported cookies for https://www.overleaf.com
```

At the name prompt you can also paste a whole `Cookie:` request header (`a=1; b=2`) copied from the Network tab.

**Command line** — handy for scripts, but the value ends up in shell history:

```bash
leaflink auth import --base-url https://overleaf.example.com --cookie 'sharelatex.sid=s%3A...'
```

**JSON file**:

```bash
leaflink auth import --base-url https://www.overleaf.com --cookie-file cookies.json
```

```json
[
  {"name": "overleaf_session2", "value": "s%3A...", "domain": ".overleaf.com"}
]
```

- `name` and `value` are required.
- `domain` is optional and defaults to the `--base-url` host (`.overleaf.com` for the official sites).
- `path`, `secure` and `httpOnly` are optional.
- `{"cookies": [...]}` exports from browser cookie extensions and a plain `{"overleaf_session2": "s%3A..."}` object are also accepted.

`leaflink login` accepts the same `--cookie-file` / `--cookie` options. Run `leaflink list` afterwards to
check the session works; `leaflink auth import --help` shows this reference offline.

### Logout

```bash
leaflink logout
```

Example output:

```text
[ok] Removed saved auth session.
```

## Quick Start

```bash
leaflink login --base-url https://cn.overleaf.com
leaflink list
leaflink clone "Sample Paper Draft"
cd sample-paper-draft
leaflink status
leaflink pull
leaflink push
leaflink download --output build/output.pdf
leaflink sync
```

## Commands and Sample Output

All project names, IDs, paths, and file contents below are fictional examples.

### `leaflink list`

Lists all Overleaf projects accessible to the current account. It is useful before cloning so you can confirm project names, IDs, and recent update times.

```bash
leaflink list
```

```text
Name                         Project ID                Updated
---------------------------  ------------------------  ------------------------
Sample Paper Draft          a1b2c3d4e5f60718293a4b5c  2026-03-27T09:16:42.180Z
Research Notes              b2c3d4e5f60718293a4b5c6d  2026-03-24T12:08:09.011Z
Resume Template CN          c3d4e5f60718293a4b5c6d7e  2026-03-21T07:45:33.501Z
```

### `leaflink clone`

Clones a remote project into a local directory and initializes the `.leaflink/` metadata used to track the mapping between the local workspace and the remote project.

```bash
leaflink clone a1b2c3d4e5f60718293a4b5c
leaflink clone "Sample Paper Draft"
leaflink clone https://www.overleaf.com/project/a1b2c3d4e5f60718293a4b5c ./paper-demo
```

```text
[ok] Cloned Sample Paper Draft into sample-paper-draft
```

### `leaflink status`

Analyzes local and remote changes without applying anything. Use it to preview added, modified, deleted, and conflicting files before a pull or push.

```bash
leaflink status
```

```text
[local] added: figures/overview.pdf
[local] modified: main.tex
[local] deleted: -
[remote] added: appendix.tex
[remote] modified: refs.bib
[remote] deleted: drafts/old-outline.tex
[conflicts] -
```

### `leaflink pull`

Pulls the latest remote changes into the local project directory. It handles additions, updates, deletions, and enters conflict resolution when overlapping text edits are detected.

```bash
leaflink pull
leaflink pull --conflict-strategy keep-remote
```

```text
[2026-03-27 14:06:11] [remote] changed: refs.bib (saved 2026-03-27 14:05:57, by collaborator)
[2026-03-27 14:06:11] [pull] updated: refs.bib (saved 2026-03-27 14:05:57, by collaborator)
[2026-03-27 14:06:11] [pull] added: appendix.tex
```

Conflict example:

```text
[2026-03-27 14:06:11] [conflict] main.tex
Local and remote edits overlap in the same text region.
...
<<<<<<< local/main.tex
\title{Sample Paper Draft v2}
||||||| base/main.tex
\title{Sample Paper Draft}
=======
\title{Sample Paper Draft Revised}
>>>>>>> remote/main.tex
Choose a resolution:
1. keep remote
2. keep local
3. duplicate both
```

### `leaflink push`

Pushes local changes to the remote project. It tries to upload only changed files and works for common binary assets as well as text sources.

```bash
leaflink push
leaflink push --dry-run
```

```text
[2026-03-27 14:07:42] [push] uploaded: main.tex (saved 2026-03-27 14:07:38)
[2026-03-27 14:07:42] [push] uploaded: figures/overview.pdf (saved 2026-03-27 14:07:11)
```

### `leaflink download`

Downloads the most recent compiled PDF from the remote project. This is useful for local archiving, submission workflows, or build pipelines.

```bash
leaflink download
leaflink download --output build/paper.pdf
```

```text
[ok] Downloaded PDF to /path/to/project/build/paper.pdf
```

### `leaflink sync`

Starts the pseudo real-time sync loop. It watches local file changes and pushes them automatically, while polling the remote project on an interval and pulling remote changes when safe.

```bash
leaflink sync
leaflink sync --interval 15 --debounce 2.0
leaflink sync --once
```

```text
[2026-03-27 13:21:23] [sync] Preparing sync service for Sample Paper Draft.
[2026-03-27 13:21:23] [sync] Project lock acquired for Sample Paper Draft.
[2026-03-27 13:21:23] [sync] Starting local watcher.
[2026-03-27 13:21:23] [sync] Sync service started. Watching /path/to/project (remote poll: 10.0s, debounce: 1.5s).
[2026-03-27 13:21:31] [local] modified: main.tex (saved 2026-03-27 13:21:30)
[2026-03-27 13:21:33] [push] uploaded: main.tex (saved 2026-03-27 13:21:30)
[2026-03-27 13:21:43] [sync] Checking remote changes.
[2026-03-27 13:21:44] [remote] changed: refs.bib (saved 2026-03-27 13:21:40, by collaborator)
[2026-03-27 13:21:44] [pull] updated: refs.bib (saved 2026-03-27 13:21:40, by collaborator)
```

## `.leafignore` Example

```gitignore
# LeafLink metadata
.leaflink/

# Git
.git/

# macOS
.DS_Store

# LaTeX temporary files
*.aux
*.log
*.out
*.fls
*.fdb_latexmk
*.synctex.gz
*.synctex(busy)

# Custom rules
build/
dist/
```

See [examples/leafignore.example](examples/leafignore.example) for a complete example.

## Conflict Handling

LeafLink uses three-way merge with:

- a shared base snapshot
- the current local file
- the current remote file

Behavior:

- non-overlapping text edits are merged when possible
- overlapping text edits enter conflict resolution
- binary files are not auto-merged

Available strategies:

1. `keep remote`
2. `keep local`
3. `duplicate both`

## How `sync` Works and Its Limits

`leaflink sync` is pseudo real-time sync, not true live collaborative editing.

It works by:

- watching the local directory with `watchdog`
- debouncing bursts of local writes
- polling the remote project at intervals
- applying automatic push / pull when safe
- entering conflict resolution when overlapping edits are detected

Limitations:

- remote changes are discovered by polling, not server push
- text files are better candidates for auto-merge than binary files
- if Overleaf private web APIs change, some write paths may need updates

## Local Metadata

Each cloned project stores internal metadata in:

```text
.leaflink/
  project.json
  state.json
  lock
  cache/
  logs/
```

## Security Notes

- LeafLink does not store plaintext passwords
- only required session cookies and metadata are persisted
- delete cookie files after importing them (or use the interactive prompt, which leaves nothing on disk)
- logs avoid printing sensitive auth values by default
- storing sessions is best done on trusted personal devices only

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=xiongqi123123/LeafLink&type=Date)](https://star-history.com/#xiongqi123123/LeafLink&Date)

## Development and Release

- install dev dependencies: `pip install -e ".[dev,browser,watch]"`
- run tests: `python -m unittest discover -s tests -v`
- build locally: `python scripts/build_dist.py`
- GitHub Actions:
  - CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
  - Publish: [`.github/workflows/publish.yml`](.github/workflows/publish.yml)

## License

This project is licensed under the [Apache License 2.0](LICENSE.txt).
