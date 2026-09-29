"""Exercise both documented packaging entry points against immutable Git data."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import package_release
from verify_release_source import verify_source
from verify_release_archive import verify

BASH = 'C:/Programas/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
VERSION = '0.0.75'
# Small source-owned packager produces the real mod format, including checksums.
PACKAGER = '''import argparse, hashlib, pathlib, zipfile
p=argparse.ArgumentParser();p.add_argument('--out');a=p.parse_args()
r=pathlib.Path('.');out=pathlib.Path(a.out);out.mkdir(parents=True)
files={str(p).replace('\\\\','/'):p.read_bytes() for p in r.rglob('*') if p.is_file()}
sums=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\\n' for name,data in sorted(files.items()))
files['SHA256SUMS.txt']=sums.encode()
import json
version=json.loads(files['manifest.json'])['version']
with zipfile.ZipFile(out/('stadium_realtime_combat_'+version+'.zip'),'w') as z:
 for name,data in sorted(files.items()):
  info=zipfile.ZipInfo(name,(2026,9,16,0,0,0));info.external_attr=0o100644<<16;z.writestr(info,data)
'''


class Packaging(unittest.TestCase):
    def git(self, source, *args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()

    def fixture(self, root):
        source = root / 'source'; source.mkdir(); (source / 'tools').mkdir()
        (source / '.github').mkdir(); (source / '.github/secret.txt').write_text('excluded')
        (source / '.gitignore').write_text('excluded')
        (source / 'manifest.json').write_text(json.dumps(dict(
            id='stadium_realtime_combat', entry='main.lua', version='0.0.1', github='private')))
        (source / 'main.lua').write_text('mod.exports.version = "0.0.1"\n')
        (source / 'payload.txt').write_text('committed source')
        (source / 'tools/package.py').write_text(PACKAGER, encoding='utf-8', newline='\n')
        self.git(source, 'init', '-q')
        self.git(source, 'add', '.')
        self.git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'immutable source')
        sha = self.git(source, 'rev-parse', 'HEAD')
        (source / 'payload.txt').write_text('uncommitted work must be ignored')
        return source, sha

    def execute(self, command, root, variables):
        prefix = 'set -euo pipefail\nfunction python3(){ "' + sys.executable.replace('\\', '/') + '" "$@"; }\n'
        env = {**os.environ, **{k: str(v).replace('\\', '/') for k,v in variables.items()}}
        result = subprocess.run([BASH, '-c', prefix + command], cwd=root, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_and_recovery_outputs_match(self):
        workflow = (ROOT / '.github/workflows/publish.yml').read_text()
        self.assertIn('python3 scripts/isolated_release.py', workflow)
        run = 'python3 scripts/package_release.py --source source --source-sha "$SOURCE_SHA" --version "$VERSION" --out dist'
        doc = (ROOT / 'docs/release-recovery.md').read_text()
        recovery = re.search(r'python3 "\$RECIPE_DIR/scripts/package_release.py".*?--out "\$DIST_DIR"', doc, re.S)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, sha = self.fixture(root)
            # Workflow uses relative source/scripts; recovery uses explicit isolated paths.
            shutil.copytree(ROOT / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            self.execute(run, root, dict(SOURCE_SHA=sha, VERSION=VERSION))
            self.execute(recovery, root, dict(RECIPE_DIR=ROOT, SOURCE_DIR=source,
                                            SOURCE_SHA=sha, VERSION=VERSION, DIST_DIR=root / 'recovered'))
            for name in ('stadium_realtime_combat-' + VERSION + '.zip', 'SHA256SUMS.txt'):
                self.assertEqual((root / 'dist' / name).read_bytes(), (root / 'recovered' / name).read_bytes())
            package = root / 'dist' / ('stadium_realtime_combat-' + VERSION + '.zip')
            verify(package, VERSION)
            with zipfile.ZipFile(package) as z:
                self.assertEqual(z.read('payload.txt'), b'committed source')
                self.assertFalse(any(n.startswith('.github/') or n == '.gitignore' for n in z.namelist()))
            self.assertEqual((source / 'payload.txt').read_text(), 'uncommitted work must be ignored')
            self.assertEqual((root / 'dist/SHA256SUMS.txt').read_bytes(),
                             (hashlib.sha256(package.read_bytes()).hexdigest() + '  ' + package.name + '\n').encode())

    def test_explicit_old_commit_survives_new_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            self.git(source, 'add', 'payload.txt')
            self.git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '-qm', 'later source')
            package=package_release.build(source, sha, VERSION, root / 'out')
            with zipfile.ZipFile(package) as z:
                self.assertEqual(z.read('payload.txt'), b'committed source')

    def test_source_proof_matches_exact_commit_and_rejects_valid_other_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            good=package_release.build(source,sha,VERSION,root/'good').read_bytes()
            verify_source(good,source,sha,VERSION)
            self.git(source,'add','payload.txt')
            self.git(source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                     'commit','-qm','different private source')
            other=self.git(source,'rev-parse','HEAD')
            wrong=package_release.build(source,other,VERSION,root/'wrong')
            verify(wrong,VERSION)  # Self-consistent versions, metadata and embedded checksums.
            with self.assertRaisesRegex(ValueError,'differs from the declared source'):
                verify_source(wrong.read_bytes(),source,sha,VERSION)
            verify_source(good,source,sha,VERSION)  # Later HEAD cannot change the pinned rebuild.
            self.assertEqual((source/'payload.txt').read_text(),'uncommitted work must be ignored')

    def test_source_proof_cli_and_missing_commit_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            good=package_release.build(source,sha,VERSION,root/'good').read_bytes()
            args=[sys.executable,str(ROOT/'scripts/verify_release_source.py'),
                  '--source',str(source),'--source-sha',sha,'--version',VERSION]
            completed=subprocess.run(args,input=good,capture_output=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            args[args.index(sha)]='f'*40
            self.assertNotEqual(subprocess.run(args,input=good,capture_output=True).returncode,0)

    def test_invalid_inputs_stop_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            for candidate,version in [('main', VERSION), ('f'*40, VERSION), (sha, 'v0.0.75')]:
                with self.subTest(candidate=candidate,version=version), self.assertRaises((ValueError,subprocess.CalledProcessError)):
                    package_release.build(source,candidate,version,root/'out')
                self.assertFalse((root/'out').exists())

    def test_recovery_pins_recipe_from_original_run(self):
        doc = (ROOT / 'docs/release-recovery.md').read_text()
        start = doc.index('gh api "repos/Neburb/legends/actions/runs/$RUN_ID"')
        end = doc.index('\ntest -s "$ZIP"', start)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            public=root/'public';public.mkdir()
            shutil.copytree(ROOT/'scripts',public/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
            self.git(public,'init','-q');self.git(public,'add','scripts')
            identity=['-c','user.name=Fixture','-c','user.email=fixture@example.invalid']
            self.git(public,*identity,'commit','-qm','original recipe')
            original=self.git(public,'rev-parse','HEAD')
            self.git(public,'remote','add','origin',str(public))
            # Today's recipe no longer builds these bytes; the original one must still work.
            (public/'scripts/package_release.py').write_text('raise SystemExit("later recipe")\n')
            self.git(public,'add','scripts/package_release.py')
            self.git(public,*identity,'commit','-qm','later incompatible recipe')
            (root/'run-input.json').write_text(json.dumps(dict(path='.github/workflows/publish.yml',head_sha=original)))
            command='function gh(){ cat run-input.json; }\n'+doc[start:end]
            self.execute(command,root,dict(PUBLIC_DIR=public,RUN_ID='123',RECOVERY_DIR=root,
                RECIPE_DIR=root/'recipe',SOURCE_DIR=source,SOURCE_SHA=sha,VERSION=VERSION,DIST_DIR=root/'out'))
            self.assertEqual(self.git(root/'recipe','rev-parse','HEAD'),original)
            verify(root/'out'/('stadium_realtime_combat-'+VERSION+'.zip'),VERSION)


if __name__ == '__main__':
    unittest.main()
