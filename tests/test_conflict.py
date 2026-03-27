from __future__ import annotations

import unittest

import bootstrap
from leaflink.sync.conflict import analyze_conflict


class ConflictTests(unittest.TestCase):
    def test_analyze_conflict_auto_merges_distinct_regions(self) -> None:
        base = b"title: old\nbody: old\nfooter: old\n"
        local = b"title: local\nbody: old\nfooter: old\n"
        remote = b"title: old\nbody: old\nfooter: remote\n"

        analysis = analyze_conflict("main.tex", base, local, remote)

        self.assertTrue(analysis.can_auto_merge)
        self.assertEqual(
            analysis.merged_content,
            b"title: local\nbody: old\nfooter: remote\n",
        )

    def test_analyze_conflict_reports_merge3_markers_for_overlap(self) -> None:
        base = b"line1\nline2\nline3\n"
        local = b"line1\nLOCAL\nline3\n"
        remote = b"line1\nREMOTE\nline3\n"

        analysis = analyze_conflict("resume.tex", base, local, remote)

        self.assertFalse(analysis.can_auto_merge)
        self.assertEqual(analysis.reason, "Local and remote edits overlap in the same text region.")
        self.assertIsNotNone(analysis.preview)
        assert analysis.preview is not None
        self.assertIn("<<<<<<< local/resume.tex", analysis.preview)
        self.assertIn("||||||| base/resume.tex", analysis.preview)
        self.assertIn(">>>>>>> remote/resume.tex", analysis.preview)
