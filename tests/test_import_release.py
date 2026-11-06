import importlib.util
from pathlib import Path
import tempfile
import json
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('importer', Path(__file__).resolve().parents[1] / 'scripts/import_release.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def release_files(text=b'<html>test</html>'):
    files = {name: ('source fixture ' + name).encode()
             for name in importer.REQUIRED | importer.NATIVE_INPUTS}
    files.update({
        'index.html': text, 'synth-huc6280/index.html': text,
        'synth-huc6280/synth.js': b'// readable app', 'synth-huc6280/processor.js': b'// processor',
        'synth-huc6280/synth.css': b'body {}', 'js/huc6280_wasm.js': b'// readable wrapper',
        'generated/huc6280_wasm.js': b'// generated factory',
        'generated/huc6280_wasm.wasm': b'\x00asm\x01\x00\x00\x00',
        'sources/huc6280-synth-browser-inputs.zip': bytes(range(256)),
    })
    def record(name):
        return {'path': name, 'bytes': len(files[name]), 'sha256': importer.digest(files[name])}
    entries = ['synth-huc6280/synth.js', 'synth-huc6280/processor.js', 'synth-huc6280/synth.css']
    modules = [{**record(name), 'sourcePath': 'docs/' + name, 'localImports':
                ['../generated/huc6280_wasm.js', '../js/huc6280_wasm.js'] if name.endswith('/processor.js') else []}
               for name in [*entries, 'js/huc6280_wasm.js']]
    files['sources/huc6280-synth-browser.json'] = json.dumps({
        'productId': 'tetorica-huc6280-synth', 'builder': {'name': 'source-copy', 'minify': False, 'bundle': False},
        'bundles': [record(name) for name in entries], 'modules': modules,
        'originalInputs': [{'path': item['sourcePath'], 'bytes': item['bytes'], 'sha256': item['sha256']} for item in modules],
        'sourceArchive': record('sources/huc6280-synth-browser-inputs.zip'),
    }).encode()
    files['sources/HuC6280.json'] = json.dumps({
        'component': 'huc6280', 'inputs': [record(name) for name in sorted(importer.NATIVE_INPUTS)],
        # HuC6280 generated records do not carry their own path property.
        'generated': {name: {key: value for key, value in record('generated/' + name).items() if key != 'path'}
                      for name in ['huc6280_wasm.js', 'huc6280_wasm.wasm']},
    }).encode()
    return files

def write_archive(path, files):
    with zipfile.ZipFile(path, 'w') as output:
        for name, data in files.items():
            output.writestr(name, data)


class ImportTests(unittest.TestCase):
    def test_new_zip_updates_without_version_and_preserves_label_for_same_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'any-name.zip'
            write_archive(archive, release_files(b'first'))
            first = importer.import_release(root, archive)
            first['version'] = 'named-release'
            (root / 'release.lock.json').write_text(json.dumps(first))
            self.assertEqual(importer.import_release(root, archive)['version'], 'named-release')
            write_archive(archive, release_files(b'second'))
            changed = importer.import_release(root, archive)
            self.assertNotEqual(changed['sha256'], first['sha256'])
            self.assertEqual(changed['version'], 'sha256-' + changed['sha256'][:12])
            self.assertEqual((root / 'dist/index.html').read_text(), 'second')
            self.assertEqual(importer.check(root), changed)

    def test_invalid_replacement_preserves_dist_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'release.zip'
            write_archive(archive, release_files(b'valid'))
            first = importer.import_release(root, archive)
            write_archive(archive, {'index.html': b'wrong app'})
            with self.assertRaises(ValueError):
                importer.import_release(root, archive)
            self.assertEqual(importer.check(root), first)
            self.assertEqual((root / 'dist/index.html').read_text(), 'valid')

    def unpack(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'release.zip'
            write_archive(archive, files)
            return importer.unpack(archive, root / 'out')

    def test_preserves_all_original_bytes(self):
        files = release_files()
        self.assertEqual(self.unpack(files), {name: importer.digest(data) for name, data in files.items()})

    def test_check_detects_modified_or_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dist').mkdir()
            target = root / 'dist/index.html'
            target.write_bytes(b'original')
            (root / 'release.lock.json').write_text(json.dumps({'version': 'test', 'files': {'index.html': importer.digest(b'original')}}))
            self.assertEqual(importer.check(root)['version'], 'test')
            target.write_bytes(b'changed')
            with self.assertRaises(ValueError): importer.check(root)
            target.write_bytes(b'original')
            (root / 'dist/extra.js').write_bytes(b'extra')
            with self.assertRaises(ValueError): importer.check(root)

    def test_rejects_traversal(self):
        for name in ['../escape', '/absolute', 'a/../../escape', 'a\\escape', 'C:/escape']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.unpack({name: b'bad'})

    def test_rejects_wrong_release_or_missing_wasm_and_sources(self):
        with self.assertRaises(ValueError): self.unpack({'index.html': b'wrong app'})
        for name in ['generated/huc6280_wasm.js', 'generated/huc6280_wasm.wasm',
                     'sources/HuC6280.json', 'sources/huc6280-synth-browser-inputs.zip']:
            files = release_files(); del files[name]
            with self.subTest(name=name), self.assertRaises(ValueError): self.unpack(files)

    def test_rejects_mismatched_receipts_and_changed_native_or_browser_bytes(self):
        for name in ['generated/huc6280_wasm.wasm', 'synth-huc6280/synth.js',
                     'js/huc6280_wasm.js', 'sources/huc6280-sdk/vendor/mame-huc6280/huc6280.cpp',
                     'sources/huc6280-synth-browser-inputs.zip']:
            files = release_files(); files[name] = b'changed'
            with self.subTest(name=name), self.assertRaises(ValueError): self.unpack(files)
        files = release_files()
        receipt = json.loads(files['sources/huc6280-synth-browser.json'])
        receipt['productId'] = 'tetorica-spu-synth'
        files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
        with self.assertRaises(ValueError): self.unpack(files)

    def test_every_readable_module_matches_its_live_bytes_and_original_input_record(self):
        files = release_files()
        receipt = json.loads(files['sources/huc6280-synth-browser.json'])
        receipt['modules'][-1]['sha256'] = '0' * 64
        files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, 'receipt mismatch'): self.unpack(files)
        files = release_files()
        receipt = json.loads(files['sources/huc6280-synth-browser.json'])
        receipt['originalInputs'][-1]['sha256'] = '0' * 64
        files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, 'original source'): self.unpack(files)

    def test_readable_module_graph_cannot_omit_a_dependency_or_an_entry(self):
        for omitted in ['js/huc6280_wasm.js', 'synth-huc6280/synth.js']:
            files = release_files()
            receipt = json.loads(files['sources/huc6280-synth-browser.json'])
            receipt['modules'] = [item for item in receipt['modules'] if item['path'] != omitted]
            files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
            with self.subTest(omitted=omitted), self.assertRaises(ValueError): self.unpack(files)
        files = release_files()
        del files['js/huc6280_wasm.js']
        with self.assertRaisesRegex(ValueError, 'Missing recorded'): self.unpack(files)

    def test_huc6280_requires_licenses_and_complete_native_sdk_sources(self):
        for name in ['licenses/mame-huc6280/LICENSE', 'licenses/mame-huc6280/README.md',
                     'sources/huc6280-sdk/vendor/mame-huc6280/LICENSE',
                     'sources/huc6280-sdk/scripts/build-wasm.sh',
                     'sources/huc6280-sdk/vendor/mame-huc6280/upstream/c6280.cpp']:
            files = release_files(); del files[name]
            with self.subTest(name=name), self.assertRaises(ValueError): self.unpack(files)
        files = release_files()
        receipt = json.loads(files['sources/HuC6280.json'])
        receipt['inputs'] = [item for item in receipt['inputs'] if not item['path'].endswith('huc6280.h')]
        files['sources/HuC6280.json'] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, 'core, wrapper'): self.unpack(files)
        files = release_files()
        receipt = json.loads(files['sources/HuC6280.json']); receipt['component'] = 'gameboy_apu'
        files['sources/HuC6280.json'] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, 'HuC6280'): self.unpack(files)

    def test_malformed_or_unsafe_module_records_are_rejected(self):
        for replacement in [[], [None], [{'path': '../escape'}]]:
            files = release_files()
            receipt = json.loads(files['sources/huc6280-synth-browser.json']); receipt['modules'] = replacement
            files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
            with self.subTest(replacement=replacement), self.assertRaises(ValueError): self.unpack(files)
        files = release_files()
        receipt = json.loads(files['sources/huc6280-synth-browser.json'])
        receipt['modules'][0]['localImports'] = ['../../escape.js']
        files['sources/huc6280-synth-browser.json'] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, 'Unsafe'): self.unpack(files)

    def test_rejects_duplicate_names_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'release.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('index.html', b'a')
                with self.assertWarns(UserWarning): output.writestr('index.html', b'b')
            with self.assertRaisesRegex(ValueError, 'Duplicate'): importer.unpack(archive, root / 'out')
            with zipfile.ZipFile(archive, 'w') as output:
                info = zipfile.ZipInfo('link'); info.create_system = 3
                info.external_attr = 0o120777 << 16
                output.writestr(info, '../../escape')
            with self.assertRaisesRegex(ValueError, 'Unsafe'): importer.unpack(archive, root / 'out2')


if __name__ == '__main__':
    unittest.main()
