import hashlib
import zipfile
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gates', ROOT / 'scripts/verify_recovery_state.py')
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)
TAG = 'v0.0.75'
SHA = 'a' * 40
BLOCKS = re.findall(r'```bash\n(.*?)\n```', (ROOT / 'docs/release-recovery.md').read_text(), re.S)
BASH = 'C:/Programas/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')

class Gates(unittest.TestCase):
    def release(self):
        return dict(tag_name=TAG, draft=True, body='Notes\nSource: https://github.com/Neburb/gen1recomp-legends/commit/' + SHA)

    def test_metadata(self):
        for legacy in (False, True):
            release = self.release()
            if legacy: release['body'] = release['body'].replace('\n', '\\n')
            gates.verify_metadata(release, TAG, SHA)

    def test_wrong_metadata_stops(self):
        for key, value in [('tag_name', 'v0.0.76'), ('draft', False), ('body', ''),
                           ('body', self.release()['body'].replace(SHA, 'b' * 40)),
                           ('body', self.release()['body'] + '\n' + self.release()['body'].splitlines()[-1])]:
            release = self.release(); release[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                gates.verify_metadata(release, TAG, SHA)

    def stub(self, state='disabled_manually', pages=None):
        calls = []
        def run(args, **kw):
            path = args[-1]; calls.append(path)
            if '/runs?' not in path: return json.dumps({'state': state})
            return json.dumps({'workflow_runs': pages[int(path.split('page=')[-1]) - 1]})
        return run, calls

    def test_disabled_and_drained(self):
        run, calls = self.stub(pages=[[{'status': 'completed'}] * 100, []])
        gates.verify_quiescent(run)
        self.assertEqual(len(calls), 3)

    def test_active_workflow_and_all_pending_statuses_stop(self):
        run, _ = self.stub(state='active', pages=[[]])
        with self.assertRaises(ValueError): gates.verify_quiescent(run)
        for status in ('in_progress', 'queued', 'waiting', 'pending', 'requested'):
            run, _ = self.stub(pages=[[{'status': 'completed'}] * 100, [{'status': status}]])
            with self.subTest(status=status), self.assertRaises(ValueError): gates.verify_quiescent(run)

    def bash(self, script, cwd):
        result = subprocess.run([BASH, '-c', script], cwd=cwd, text=True, capture_output=True)
        return result

    def test_all_documented_blocks_parse(self):
        for block in BLOCKS:
            result = subprocess.run([BASH, '-n'], input=block, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_initial_empty_draft_skips_download(self):
        block = BLOCKS[0]
        start = block.index('ASSET_COUNT=')
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for assets in ([], [{'name': 'original.zip'}]):
                (root / 'release-before.json').write_text(json.dumps({'assets': assets}))
                script = 'set -euo pipefail\nRECOVERY_DIR=.\nTAG=v0.0.75\nDOWNLOADED_DIR=.\nfunction python3(){ "' + sys.executable.replace('\\', '/') + '" "$@"; }\nfunction gh(){ echo download; }\n' + block[start:]
                result = self.bash(script, directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('download' in result.stdout, bool(assets))

    def test_empty_rollback_deletes_new_assets_and_stays_hidden(self):
        block = next(b for b in BLOCKS if b.startswith('# Existing releases only.'))
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'backup').mkdir()
            (root / 'state.json').write_text(json.dumps({'draft': True, 'assets': [{'name': 'new.zip'}, {'name': 'SHA256SUMS.txt'}]}))
            # Execute the actual inline Python with only GH subprocess operations replaced.
            (root / 'mock_python.py').write_text('''import sys,json,pathlib,subprocess
state=pathlib.Path('state.json')
if len(sys.argv)>1 and sys.argv[1].endswith('verify_recovery_state.py'):
    assert sys.argv[2]=='quiescent';sys.exit()
if len(sys.argv)>1 and sys.argv[1].endswith('inspect_recovery_release.py'):
    print(state.read_text());sys.exit()
def output(args,**kw):return state.read_text()
def run(args,**kw):
    assert args[1:3]==['release','delete-asset']
    data=json.loads(state.read_text());data['assets']=[a for a in data['assets'] if a['name']!=args[4]];state.write_text(json.dumps(data))
subprocess.check_output=output;subprocess.run=run
sys.argv=sys.argv[1:];exec(sys.stdin.read(),{'__name__':'__main__'})
''')
            prefix = 'set -euo pipefail\nRELEASE_KIND=draft\nTAG=v0.0.75\nPUBLIC_DIR=.\nRECOVERY_DIR=.\nDOWNLOADED_DIR=./backup\nfunction gh(){ echo "unexpected GH operation: $*" >&2; return 1; }\nfunction python3(){ "' + sys.executable.replace('\\', '/') + '" mock_python.py "$@"; }\n'
            result = self.bash(prefix + block, directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / 'state.json').read_text()), {'draft': True, 'assets': []})

    def test_repair_gate_precedes_writes_and_metadata_blocks_upload(self):
        block = next(b for b in BLOCKS if 'if [ "$RELEASE_KIND" = published ]; then' in b)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            prefix = 'set -euo pipefail\nTAG=v0.0.75\nSOURCE_SHA=' + SHA + '\nPUBLIC_DIR="' + ROOT.as_posix() + '"\nRECOVERY_DIR=.\nZIP=mock.zip\nSUMS=mock.sums\nVERSION=0.0.75\nfunction gh(){ echo "$*"; }\n'
            for kind, drained, correct, success in [('published', False, True, False), ('draft', True, False, False), ('draft', True, True, True), ('published', True, True, True), ('orphan', True, True, True)]:
                release = self.release()
                if not correct: release['body'] = ''
                (root / 'mock.json').write_text(json.dumps(release))
                wrapper = 'function python3(){ if [[ "$1" == *inspect_recovery_release.py ]]; then cat mock.json; elif [ "${2:-}" = quiescent ]; then return ' + ('0' if drained else '1') + '; else "' + sys.executable.replace('\\', '/') + '" "$@"; fi; }\n'
                result = self.bash(prefix + wrapper + 'RELEASE_KIND=' + kind + '\n' + block, directory)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                if not drained: self.assertNotIn('release edit', result.stdout)
                if not success: self.assertNotIn('release upload', result.stdout)
                if kind == 'published' and success: self.assertLess(result.stdout.index('--draft=true'), result.stdout.index('release upload'))
                if kind == 'orphan' and success: self.assertIn('--verify-tag --draft', result.stdout)

    def test_verification_compares_both_assets_before_publication(self):
        block = next(b for b in BLOCKS if b.startswith('VERIFIED_DIR='))
        # Run the exact comparison commands on freshly downloaded mock files.
        comparison = '\n'.join(line for line in block.splitlines() if line.startswith('cmp "$ZIP"') or line.startswith('cmp "$SUMS"'))
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); (root / 'verified').mkdir()
            (root / 'expected.zip').write_bytes(b'rebuilt source bytes')
            (root / 'expected.sums').write_bytes(b'expected checksum')
            for zip_bytes, sums_bytes, success in [(b'rebuilt source bytes', b'expected checksum', True), (b'other same-version package', b'expected checksum', False), (b'rebuilt source bytes', b'other checksum', False)]:
                (root / 'verified/package.zip').write_bytes(zip_bytes)
                (root / 'verified/SHA256SUMS.txt').write_bytes(sums_bytes)
                result = self.bash('set -euo pipefail\nZIP=expected.zip\nSUMS=expected.sums\nVERIFIED_DIR=verified\nZIP_NAME=package.zip\n' + comparison, directory)
                self.assertEqual(result.returncode == 0, success)
        self.assertIn('metadata "$RECOVERY_DIR/release-verified.json" "$TAG" "$SOURCE_SHA"', block)
        final = BLOCKS[-1]
        self.assertLess(final.index(' quiescent'), final.index('--draft=false'))

    def test_same_version_self_consistent_wrong_package_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name, content in [('rebuilt.zip', 'recorded source'), ('downloaded.zip', 'another source')]:
                files = {'manifest.json': json.dumps(dict(id='stadium_realtime_combat', entry='main.lua', version='0.0.75', github='Neburb/legends')).encode(),
                         'main.lua': b'return function(mod) mod.exports.version="0.0.75" end',
                         'payload.txt': content.encode()}
                files['SHA256SUMS.txt'] = ''.join(hashlib.sha256(value).hexdigest() + '  ' + key + '\n' for key, value in files.items()).encode()
                with zipfile.ZipFile(root / name, 'w') as archive:
                    for key, value in files.items(): archive.writestr(key, value)
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_release_archive.py'), str(root / name), '0.0.75'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            result = self.bash('set -euo pipefail\ncmp rebuilt.zip downloaded.zip', directory)
            self.assertNotEqual(result.returncode, 0)

if __name__ == '__main__': unittest.main()
