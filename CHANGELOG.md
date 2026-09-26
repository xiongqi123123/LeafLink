# Changelog

## 0.3.5 — 2026-09-27

- `leaflink auth import` without `--cookie-file` now prompts for cookie names and hidden values,
  so a headless server can be authenticated without writing a JSON file. Pasting a full
  `Cookie:` header (`a=1; b=2`) at the name prompt is also supported.
- Add repeatable `--cookie NAME=VALUE` to `login` and `auth import` for scripted setups.
- Cookie files: `domain` is now optional (defaults to the `--base-url` host, `.overleaf.com` for
  the official sites) and a plain `{"NAME": "VALUE"}` object is accepted.
- Invalid cookie files report what is wrong together with the expected format instead of a traceback.
- `login --help` and `auth import --help` document where to find the session cookie
  (`overleaf_session2` / `sharelatex.sid`) and show a cookie file example.
- `leaflink login` explains how to use `auth import` when no browser window can be opened.
- Preserve the `httpOnly` flag of imported cookies.
- README: step-by-step cookie import guide for servers without a browser.

## 0.3.0 — 2026-09-23

- Add explicit self-hosted Overleaf HTTP(S) origins and project URL recognition.
- Scope browser login and imported cookies to the selected instance.
- Apply ignore rules to local and remote changes, clone, pull, push and deletion.
- Reload ignore rules before synchronization checks; keep ignored historical baselines
  so adding a rule cannot masquerade as a deletion and later unignoring retains conflict detection.
- Add ordered negation, rooted and directory patterns, and segment-aware glob matching.
- Always protect Git and LeafLink metadata from synchronization.
- Add regression tests for self-hosted authentication and ignore-rule data preservation.

- Reuse upload root-folder discovery within each operation while refreshing stale entity IDs for deletions.
- Use content-only snapshots during synchronization; explicit status retains author/history details.
- Cache local hashes in each engine using device, inode, size, nanosecond modification and change times.
- Skip traversing Git and LeafLink metadata directories. Remote ZIP downloads remain necessary.

Self-hosted editor endpoints require compatibility checks against the deployed version.
No Gitea workflow is installed and no package is published by preparing this release.
