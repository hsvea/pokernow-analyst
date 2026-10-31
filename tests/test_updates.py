import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import updates
import updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def bundle(self, extras=None, bundled_version='8.1.0'):
        path = self.root / 'release.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('app/PokerNowAnalyst.exe', b'test fixture')
            z.writestr('app/PokerNowUpdater.exe', b'test fixture')
            z.writestr('bundle.json', json.dumps({'schema': 1, 'version': bundled_version}))
            z.writestr('pokernow_overlay_v2/manifest.json', json.dumps({'version': bundled_version}))
            for name, value in (extras or {}).items():
                z.writestr(name, value)
        return path, {'size': path.stat().st_size, 'version': '8.1.0', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_valid_bundle(self):
        updates.verify_archive(*self.bundle())

    def test_digest_mismatch(self):
        path, info = self.bundle()
        info['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            updates.verify_archive(path, info)

    def test_size_mismatch(self):
        path, info = self.bundle()
        info['size'] += 1
        with self.assertRaises(ValueError):
            updates.verify_archive(path, info)

    def test_wrong_version(self):
        with self.assertRaises(ValueError):
            updates.verify_archive(*self.bundle(bundled_version='7.0.0'))

    def test_reject_unexpected_user_data(self):
        with self.assertRaises(ValueError):
            updates.verify_archive(*self.bundle({'config.json': '{}'}))

    def test_case_collision(self):
        with self.assertRaises(ValueError):
            updates.verify_archive(*self.bundle({'app/POKERNOWANALYST.exe': 'duplicate'}))

    def test_reject_windows_special_names(self):
        with self.assertRaises(ValueError):
            updates.verify_archive(*self.bundle({'app/NUL.txt': 'invalid'}))

    def test_expanded_limit(self):
        path, info = self.bundle()
        with patch.object(updates, 'MAX_EXPANDED', 1), self.assertRaises(ValueError):
            updates.verify_archive(path, info)

    def release(self):
        return {'tag_name': 'v8.1.0', 'draft': False, 'prerelease': False,
                'assets': [{'name': updates.ASSET_NAME, 'state': 'uploaded', 'size': 100,
                            'digest': 'sha256:' + 'a' * 64,
                            'browser_download_url': 'https://github.com/hsvea/pokernow-analyst/releases/download/v8.1.0/' + updates.ASSET_NAME}]}

    def test_release_version_order(self):
        self.assertIsNotNone(updates.release_info(self.release(), 'hsvea/pokernow-analyst', '8.0.0'))
        self.assertIsNone(updates.release_info(self.release(), 'hsvea/pokernow-analyst', '8.1.0'))
        self.assertIsNone(updates.release_info(self.release(), 'hsvea/pokernow-analyst', '9.0.0'))

    def test_unpublished_release(self):
        release = self.release()
        release['draft'] = True
        self.assertIsNone(updates.release_info(release, 'hsvea/pokernow-analyst', '8.0.0'))

    def test_missing_digest(self):
        release = self.release()
        release['assets'][0]['digest'] = None
        with self.assertRaises((TypeError, ValueError)):
            updates.release_info(release, 'hsvea/pokernow-analyst', '8.0.0')

    def test_wrong_repository(self):
        with self.assertRaises(ValueError):
            updates.release_info(self.release(), 'other/repo', '8.0.0')

    def test_url_policy(self):
        for url in ['http://github.com/a', 'https://example.com/a', 'https://user:password@github.com/a', 'https://github.com:80/a']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                updates.validate_url(url)

    def components(self):
        root, stage, backup = [self.root / n for n in ('root', 'stage', 'backup')]
        for directory in (root, stage, backup):
            directory.mkdir()
        for directory, content in [(root, 'old'), (stage, 'new')]:
            for name in ('app', 'pokernow_overlay_v2'):
                (directory / name).mkdir()
                (directory / name / 'test.txt').write_text(content)
            (directory / 'bundle.json').write_text(content)
        return root, stage, backup

    def test_swap_and_rollback(self):
        root, stage, backup = self.components()
        moved, installed = updater.replace_components(root, stage, backup)
        self.assertEqual((root / 'app/test.txt').read_text(), 'new')
        updater.restore_components(root, backup, moved, installed)
        self.assertEqual((root / 'app/test.txt').read_text(), 'old')
        self.assertEqual((root / 'pokernow_overlay_v2/test.txt').read_text(), 'old')

    def test_partial_swap_failure_rolls_back(self):
        root, stage, backup = self.components()
        original = updater.move_retry
        def fail(source, target):
            if Path(source) == stage / 'pokernow_overlay_v2':
                raise PermissionError('fixture: file locked')
            original(source, target)
        with patch.object(updater, 'move_retry', side_effect=fail), self.assertRaises(PermissionError):
            updater.replace_components(root, stage, backup)
        self.assertEqual((root / 'app/test.txt').read_text(), 'old')
        self.assertEqual((root / 'pokernow_overlay_v2/test.txt').read_text(), 'old')
        self.assertEqual((root / 'bundle.json').read_text(), 'old')

    def test_backup_sqlite_and_settings(self):
        import sqlite3
        data = self.root / 'data'
        data.mkdir()
        db = sqlite3.connect(data / 'history.sqlite3')
        db.execute('create table example (value text)')
        db.execute("insert into example values ('preserved')")
        db.commit()
        db.close()
        (data / 'config.json').write_text('{"example":1}')
        updater.backup_data(data, self.root / 'backup')
        copy = sqlite3.connect(self.root / 'backup/history.sqlite3')
        self.assertEqual(copy.execute('select value from example').fetchone()[0], 'preserved')
        copy.close()
        self.assertEqual((self.root / 'backup/config.json').read_text(), '{"example":1}')
