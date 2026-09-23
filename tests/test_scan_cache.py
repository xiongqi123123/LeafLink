import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import bootstrap
from leaflink.sync.ignore import IgnoreMatcher
from leaflink.sync.state import scan_local_files
from leaflink.utils.hashing import sha256_file

class ScanCacheTests(unittest.TestCase):
    def test_unchanged_files_reuse_hash_and_force_rechecks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.tex').write_text('hello')
            cache = {}
            with patch('leaflink.sync.state.sha256_file', wraps=sha256_file) as digest:
                first = scan_local_files(root, IgnoreMatcher([]), cache=cache)
                self.assertEqual(first, scan_local_files(root, IgnoreMatcher([]), cache=cache))
                self.assertEqual(digest.call_count, 1)
                scan_local_files(root, IgnoreMatcher([]), cache=cache, force_hash=True)
                self.assertEqual(digest.call_count, 2)

    def test_same_size_rewrite_with_restored_mtime_is_detected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'main.tex'
            path.write_text('hello')
            before = path.stat()
            cache = {}
            first = scan_local_files(root, IgnoreMatcher([]), cache=cache)
            path.write_text('world')
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            second = scan_local_files(root, IgnoreMatcher([]), cache=cache)
            self.assertNotEqual(first['main.tex'].sha256, second['main.tex'].sha256)
            path.unlink()
            scan_local_files(root, IgnoreMatcher([]), cache=cache)
            self.assertEqual(cache, {})

    def test_sync_uses_content_snapshot_but_status_keeps_metadata(self):
        from test_sync_engine import FakeClient
        from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
        from leaflink.sync.engine import SyncEngine
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectMetadataStore(root).init(ProjectConfig(project_id='abc123', base_url='https://www.overleaf.com', project_name='Test'))
            client = FakeClient()
            client.get_sync_snapshot = client.get_project_snapshot
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive('abc123'))
            with patch.object(client, 'get_project_snapshot', side_effect=AssertionError('metadata on sync path')):
                engine.pull()
                (root / 'new.tex').write_text('new')
                engine.push()
            self.assertEqual(client.remote_files['new.tex'], b'new')
            with patch.object(client, 'get_project_snapshot', wraps=client.get_project_snapshot) as enriched:
                engine.status()
                self.assertEqual(enriched.call_count, 1)
