"""Versioned ZIP-import regressions using temporary files only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('version_importer', ROOT / 'scripts/import_release.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ImportVersionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='import app version ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / 'arbitrary-old-web-name.zip'
        with zipfile.ZipFile(self.archive, 'w') as output:
            output.writestr('index.html', 'new web app')
            output.writestr('source.js', '// readable source')
        (self.root / 'dist').mkdir()
        (self.root / 'dist/index.html').write_text('previous web app')
        (self.root / 'release.lock.json').write_bytes(b'{"version":"web-build-label","sha256":"previous","files":{}}\n')
        (self.root / importer.LOCAL_MANIFEST).write_bytes(b'{"previous":"local edits"}\n')
        self.write_json('package.json', {'name': 'fixture-tauri', 'version': '0.1.0'})
        self.write_json('package-lock.json', {
            'name': 'fixture-tauri', 'version': '0.0.5', 'lockfileVersion': 3,
            'packages': {'': {'name': 'fixture-tauri', 'version': '0.0.5'},
                         'node_modules/example': {'version': '9.8.7', 'integrity': 'unchanged'}}})
        self.write_json('src-tauri/tauri.conf.json', {'productName': 'Fixture', 'version': '0.1.0'})
        (self.root / 'src-tauri/Cargo.toml').write_text(
            '[package]\nname = "fixture-tauri"\nversion = "0.1.0"\nedition = "2021"\n')
        (self.root / 'src-tauri/Cargo.lock').write_text(
            'version = 4\n\n[[package]]\nname = "fixture-tauri"\nversion = "0.1.0"\n'
            'dependencies = ["example"]\n\n[[package]]\nname = "example"\nversion = "2.3.4"\n'
            'source = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "fixed"\n')

    def write_json(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + '\n')

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def assert_version(self, version):
        for name in ('package.json', 'package-lock.json', 'src-tauri/tauri.conf.json'):
            self.assertEqual(json.loads((self.root / name).read_text())['version'], version)
        lock = json.loads((self.root / 'package-lock.json').read_text())
        self.assertEqual(lock['packages']['']['version'], version)
        self.assertEqual(lock['packages']['node_modules/example'],
                         {'version': '9.8.7', 'integrity': 'unchanged'})
        self.assertIn(f'version = "{version}"', (self.root / 'src-tauri/Cargo.toml').read_text())
        cargo_lock = (self.root / 'src-tauri/Cargo.lock').read_text()
        self.assertIn(f'name = "fixture-tauri"\nversion = "{version}"', cargo_lock)
        self.assertIn('name = "example"\nversion = "2.3.4"', cargo_lock)

    def test_cli_import_sets_explicit_app_version_independent_of_archive_name(self):
        with mock.patch.object(importer, 'ROOT', self.root), \
             mock.patch.object(importer, 'validate_release'), \
             mock.patch.object(sys, 'argv', ['import_release.py', str(self.archive), '--version', '1.2.3']), \
             contextlib.redirect_stdout(io.StringIO()):
            importer.main()
        self.assert_version('1.2.3')
        receipt = json.loads((self.root / 'release.lock.json').read_text())
        self.assertEqual(receipt['version'], 'sha256-' + receipt['sha256'][:12])
        self.assertNotEqual(receipt['version'], '1.2.3')
        self.assertEqual((self.root / 'dist/index.html').read_text(), 'new web app')
        self.assertFalse((self.root / importer.LOCAL_MANIFEST).exists())

    def test_invalid_versions_are_rejected_without_writes(self):
        for version in ('invalid', '01.2.3', '../escape', '1.2'):
            with self.subTest(version=version):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    importer.import_release(self.root, self.archive, version=version)
                self.assertEqual(self.snapshot(), before)

    def test_invalid_metadata_is_rejected_before_distribution_change(self):
        (self.root / 'package-lock.json').write_text('{bad json')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            importer.import_release(self.root, self.archive, version='1.2.3')
        self.assertEqual(self.snapshot(), before)

    def test_invalid_zip_preserves_metadata_distribution_and_local_edits(self):
        self.archive.write_bytes(b'not a zip')
        before = self.snapshot()
        with self.assertRaises(zipfile.BadZipFile):
            importer.import_release(self.root, self.archive, version='1.2.3')
        self.assertEqual(self.snapshot(), before)

    def test_metadata_apply_failure_restores_old_distribution_and_receipts(self):
        before = self.snapshot()
        update = mock.Mock(version='1.2.3')
        update.apply.side_effect = OSError('injected metadata replace failure')
        with mock.patch.object(importer, 'prepare_app_version', return_value=update), \
             mock.patch.object(importer, 'validate_release'), \
             self.assertRaisesRegex(OSError, 'injected metadata'):
            importer.import_release(self.root, self.archive, version='1.2.3')
        self.assertEqual(self.snapshot(), before)

    def test_legacy_import_does_not_read_or_change_app_metadata(self):
        names = ('package.json', 'package-lock.json', 'src-tauri/Cargo.toml',
                 'src-tauri/Cargo.lock', 'src-tauri/tauri.conf.json')
        before = {name: (self.root / name).read_bytes() for name in names}
        with mock.patch.object(importer, 'prepare_app_version', side_effect=AssertionError('unexpected version update')), \
             mock.patch.object(importer, 'validate_release'), \
             contextlib.redirect_stdout(io.StringIO()):
            importer.import_release(self.root, self.archive)
        self.assertEqual({name: (self.root / name).read_bytes() for name in names}, before)

    def test_version_flag_is_import_only(self):
        for args in (['--version', '1.2.3'], ['--check', '--version', '1.2.3'],
                     ['--record-local-changes', '--version', '1.2.3']):
            with self.subTest(args=args):
                before = self.snapshot()
                with mock.patch.object(importer, 'ROOT', self.root), \
                     mock.patch.object(sys, 'argv', ['import_release.py', *args]), \
                     contextlib.redirect_stderr(io.StringIO()), \
                     self.assertRaises(SystemExit) as stopped:
                    importer.main()
                self.assertEqual(stopped.exception.code, 2)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
