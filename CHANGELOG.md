# Changelog

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
