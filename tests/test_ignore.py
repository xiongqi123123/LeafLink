from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap
from leaflink.sync.ignore import IgnoreMatcher


class IgnoreMatcherTests(unittest.TestCase):
    def test_matches_default_and_custom_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".leafignore").write_text("build/\n*.tmp\n# comment\n", encoding="utf-8")
            matcher = IgnoreMatcher.from_project(root)
            self.assertTrue(matcher.matches(".leaflink/state.json"))
            self.assertTrue(matcher.matches("build/output.pdf", is_dir=False))
            self.assertTrue(matcher.matches("notes.tmp"))
            self.assertTrue(matcher.matches("resume.synctex(busy)"))
            self.assertFalse(matcher.matches("main.tex"))
