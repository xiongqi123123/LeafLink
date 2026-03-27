# leaflink

`leaflink` is a new command-line tool for synchronizing a local directory with an Overleaf or cn.overleaf project, without relying on Overleaf's Git bridge.

It intentionally does **not** fork `overleaf-sync`. This project is a clean-room rewrite with a simpler architecture, stronger local state handling, clearer extension points, and an explicit pseudo real-time `sync` command.

## Why rewrite instead of fork?

- To keep the codebase clean, typed, and modular from day one.
- To separate auth, remote client behavior, project metadata, and sync logic.
- To support `overleaf.com` and `cn.overleaf.com` with the same project model.
- To add `leaflink sync`, which combines local file watching with remote polling.

## Features

- Browser-based login with persisted session cookies
- Manual cookie import fallback
- List projects
- Clone remote projects
- Pull remote changes to local
- Push local changes to remote
- Download compiled PDF
- Status inspection without syncing
- Pseudo real-time sync loop with debounce, polling, conflict detection, and per-project lock files

## Supported URLs

- `https://www.overleaf.com/project/...`
- `https://cn.overleaf.com/project/...`

## Installation

Python 3.10+ is required.

Install from PyPI:

```bash
pip install leaflink
```

After installation, use:

```bash
leaflink --help
```

Install from source:

```bash
pip install .
```

Recommended optional extras:

```bash
pip install ".[browser,watch,dev]"
```

- `browser`: installs Playwright for browser-assisted login
- `watch`: installs `watchdog` for filesystem watching
- `dev`: installs `pytest`

If you use Playwright for login, also install a browser once:

```bash
playwright install chromium
```

## Authentication

`leaflink` stores session cookies in your user config directory, not in the project directory.

Typical paths:

- macOS/Linux: `~/.config/leaflink/auth.json`
- Config file: `~/.config/leaflink/config.toml`

Only session cookies are stored. `leaflink` does **not** store your password.

### Browser login

```bash
leaflink login
leaflink login --base-url https://cn.overleaf.com
```

This opens a real browser window through Playwright. Complete login there, and `leaflink` saves the reusable session cookies.
When the dashboard/project page opens successfully, `leaflink` captures the session automatically and closes the browser for you.

### Import cookies manually

```bash
leaflink login --cookie-file cookies.json
leaflink auth import --base-url https://cn.overleaf.com --cookie-file cookies.json
```

Cookie JSON can be either a raw list or an object with a `cookies` array. Each cookie should include at least `name`, `value`, and `domain`.

## Basic usage

### Login

```bash
leaflink login
leaflink login --base-url https://cn.overleaf.com
```

### List projects

```bash
leaflink list
leaflink list --base-url https://cn.overleaf.com
```

### Clone

```bash
leaflink clone https://www.overleaf.com/project/abc123 ./paper
leaflink clone abc123 ./paper
```

### Pull

```bash
cd paper
leaflink pull
leaflink pull --conflict-strategy duplicate-both
```

### Push

```bash
leaflink push
leaflink push --dry-run
```

### Download PDF

```bash
leaflink download
leaflink download --output build/paper.pdf
```

### Status

```bash
leaflink status
```

### Pseudo real-time sync

```bash
leaflink sync
leaflink sync --interval 15 --debounce 2.0
leaflink sync --once
```

Example output:

```text
[local] modified: main.tex
[push] uploaded: main.tex
[remote] modified: refs.bib
[pull] updated: refs.bib
[conflict] figures/plot.pdf
```

## Project metadata

Every cloned project stores tool metadata inside `.leaflink/`:

```text
.leaflink/
  project.json
  state.json
  lock
  cache/
  logs/
```

- `project.json`: project id, base URL, display name, last known remote revision
- `state.json`: local snapshot, remote snapshot, last successful pull/push timestamps
- `lock`: prevents multiple `leaflink sync` loops in the same project

## Ignore rules

`leaflink` supports `.leafignore` with a gitignore-like subset:

- comments with `#`
- directory ignore patterns ending with `/`
- wildcard patterns like `*.aux`

Default ignored patterns:

- `.leaflink/`
- `.git/`
- `.DS_Store`
- `*.aux`
- `*.log`
- `*.synctex.gz`
- `*.fdb_latexmk`
- `*.fls`
- `*.out`

Example:

```text
# build artifacts
*.aux
*.log
build/

# generated figures
figures/generated/
```

## Conflict handling

When the same path changes locally and remotely, `leaflink` treats it as a conflict.
For text files, `leaflink` now uses a `merge3`-based three-way merge against the last successful sync base:

- non-overlapping edits in different regions are merged automatically
- overlapping edits stay unresolved and are shown with local/base/remote conflict context

MVP conflict strategies:

- `keep-local`: keep the local version and skip the incoming remote file
- `keep-remote`: keep the remote version and skip the outgoing local file
- `duplicate-both`: keep the local file and write the remote copy as `filename.remote.conflict.ext`

Without a strategy, `pull`, `push`, and `sync` stop and print the conflicting paths.

## How `sync` works

`leaflink sync` is **pseudo real-time sync**, not true collaborative editing.

It works like this:

1. watch the local directory for file changes
2. debounce rapid edits into one local batch
3. push local changes after the debounce window
4. poll the remote project every `--interval` seconds
5. pull remote changes when they appear
6. stop automatic handling for files that enter conflict

### Limitations

- This is not operational transform or CRDT-based collaboration.
- Simultaneous edits to the same file can still conflict.
- The default remote client can reliably read project archives and PDFs, but Overleaf write APIs are private and deployment-specific.
- The upload/delete interface is already abstracted, so site-specific endpoint mapping can be added later without rewriting the sync engine.

## Current MVP limitations

This repository includes a production-quality local architecture, tests, and a clean sync engine. Remote reads work directly over HTTP. Remote writes use the official web upload/create/delete routes together with the authenticated browser session to discover the project tree and entity ids.

That means:

- `login`, `list`, `clone`, `pull`, `push`, `status`, `download`, and `sync` are implemented end-to-end in the CLI
- full write support works best with Playwright installed because `leaflink` uses a headless authenticated browser session to discover remote entity ids safely
- private editor internals can still differ across deployments, so if a specific Overleaf installation heavily customizes its frontend, the browser-assisted tree discovery layer may need small compatibility updates

## Development

Run the tests with your environment:

```bash
python -m unittest discover -s tests -v
```

Or, if you install the dev extra:

```bash
pytest
```

## Packaging and release

Build distributable artifacts locally:

```bash
python scripts/build_dist.py
python -m twine check dist/*
```

This will produce:

- `dist/leaflink-<version>.tar.gz`
- `dist/leaflink-<version>-py3-none-any.whl`

Publish manually with a PyPI API token:

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-*** python -m twine upload dist/*
```

Or use the helper script:

```bash
scripts/release.sh check
scripts/release.sh testpypi
scripts/release.sh pypi
```

The repository also includes a GitHub Actions workflow at `.github/workflows/publish.yml`.
If you configure [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), pushing a `v*` tag can publish the package without storing a long-lived PyPI token in GitHub secrets.
