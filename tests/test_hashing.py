from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import bootstrap
from leaflink.utils.hashing import sha256_bytes, sha256_file


class HashingTests(unittest.TestCase):
    def test_sha256_helpers_match(self) -> None:
        content = b"hello leaflink"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_bytes(content)
            expected = hashlib.sha256(content).hexdigest()
            self.assertEqual(sha256_bytes(content), expected)
            self.assertEqual(sha256_file(path), expected)
