from __future__ import annotations

import unittest

import bootstrap
from leaflink.sync.diff import detect_conflicts, detect_divergence, diff_files
from leaflink.sync.state import FileFingerprint


def _fp(path: str, sha: str) -> FileFingerprint:
    return FileFingerprint(path=path, size=1, mtime=0.0, sha256=sha)


class DiffTests(unittest.TestCase):
    def test_detects_add_modify_delete_and_conflicts(self) -> None:
        baseline = {
            "main.tex": _fp("main.tex", "a"),
            "old.tex": _fp("old.tex", "b"),
        }
        local_now = {
            "main.tex": _fp("main.tex", "c"),
            "new.tex": _fp("new.tex", "d"),
        }
        remote_now = {
            "main.tex": _fp("main.tex", "e"),
            "refs.bib": _fp("refs.bib", "f"),
        }
        local_changes = diff_files(baseline, local_now)
        remote_changes = diff_files(baseline, remote_now)
        conflicts = detect_conflicts(local_changes, remote_changes)

        self.assertEqual(local_changes.added, ["new.tex"])
        self.assertEqual(local_changes.modified, ["main.tex"])
        self.assertEqual(local_changes.deleted, ["old.tex"])
        self.assertEqual(remote_changes.added, ["refs.bib"])
        self.assertEqual(remote_changes.modified, ["main.tex"])
        self.assertEqual(remote_changes.deleted, ["old.tex"])
        self.assertEqual(conflicts, ["main.tex", "old.tex"])

    def test_detect_divergence_finds_persistent_split(self) -> None:
        local_now = {
            "main.tex": _fp("main.tex", "local"),
            "notes.txt": _fp("notes.txt", "same"),
        }
        remote_now = {
            "main.tex": _fp("main.tex", "remote"),
            "notes.txt": _fp("notes.txt", "same"),
        }
        self.assertEqual(detect_divergence(local_now, remote_now), ["main.tex"])
