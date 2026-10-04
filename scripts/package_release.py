"""Build the public mod ZIP from an explicit immutable source and version.

No version allocation or GitHub writes. Recovery must use this recipe from the
public checkout recorded by the original workflow run, not today's main.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from verify_release_archive import verify


def build(source, source_sha, version, out):
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ValueError('source SHA must be 40 lowercase hex characters')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('version must be the explicit existing X.Y.Z')
    source, out = Path(source).resolve(), Path(out).resolve()
    actual = subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', source_sha + '^{commit}'], text=True).strip()
    if actual != source_sha:
        raise ValueError('source SHA must identify a commit exactly')
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', source_sha])
    with tempfile.TemporaryDirectory(prefix='legends-package-') as directory:
        staging = Path(directory) / 'source'
        staging.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(staging, filter='data')
        del archive  # Release the source buffer before the source-owned packager runs.
        for name in ('.github', '.git', '.gitattributes', '.gitignore', '.luarc.json'):
            target = staging / name
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        manifest_path = staging / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest.update(version=version, github='Neburb/legends')
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                                 encoding='utf-8', newline='\n')
        main_path = staging / 'main.lua'
        stamped, count = re.subn(r'(mod\.exports\.version\s*=\s*")[^"]+(\")',
                                 rf'\g<1>{version}\g<2>',
                                 main_path.read_text(encoding='utf-8'), count=1)
        if count != 1:
            raise ValueError('main.lua mod version declaration not found')
        main_path.write_text(stamped, encoding='utf-8', newline='\n')
        built = Path(directory) / 'dist'
        subprocess.run([sys.executable, 'tools/package.py', '--out', str(built)],
                       cwd=staging, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        package = built / f'stadium_realtime_combat_{version}.zip'
        verify(package, version)
        data = package.read_bytes()
        if not data:
            raise ValueError('empty generated ZIP')
        out.mkdir(parents=True, exist_ok=True)
        name = f'stadium_realtime_combat-{version}.zip'
        (out / name).write_bytes(data)
        (out / 'SHA256SUMS.txt').write_text(
            f'{hashlib.sha256(data).hexdigest()}  {name}\n', encoding='utf-8', newline='\n')
        return out / name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    build(args.source, args.source_sha, args.version, args.out)
