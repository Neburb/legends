"""Build the public mod ZIP from an explicit immutable source and version.

No version allocation or GitHub writes. Recovery must use this recipe from the
public checkout recorded by the original workflow run, not today's main.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from verify_release_archive import verify


PACKAGER_SUPPORT = {
    'tools/package.py', 'tools/check_engine_compatibility.py',
    'docs/IMPLEMENTATION_STATUS.md', 'docs/FORMAT_NOTES.md',
}
ALWAYS_EXCLUDED = {'.github', '.git', '.gitattributes', '.gitignore', '.luarc.json', '.modkitignore'}
CHUNK = 64 * 1024


def modkitignore_rules(source, source_sha):
    try:
        text = subprocess.check_output(
            ['git', '-C', str(source), 'show', f'{source_sha}:.modkitignore'],
            text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return set()
    rules = set()
    for raw in text.splitlines():
        rule = raw.strip().rstrip('/')
        if not rule or rule.startswith('#'):
            continue
        if (rule.startswith('/') or '\\' in rule or ':' in rule
                or any(part in ('', '.', '..') for part in rule.split('/'))
                or any(char in rule for char in '*?[]')):
            raise ValueError(f'unsupported .modkitignore entry: {raw!r}')
        rules.add(rule)
    return rules


def ignored_path(name, rules):
    name = name.rstrip('/')
    return any(name == rule or name.startswith(rule + '/') for rule in rules | ALWAYS_EXCLUDED)


def extract_installable_source(source, source_sha, staging, rules):
    """Stream the immutable Git archive and omit modkit-excluded development trees."""
    process = subprocess.Popen(
        ['git', '-C', str(source), 'archive', source_sha],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            while member := archive.next():
                name = member.name.rstrip('/')
                if ignored_path(name, rules) and name not in PACKAGER_SUPPORT:
                    continue
                archive.extract(member, path=staging, filter='data')
        if process.wait() != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise
    finally:
        if process.stdout:
            process.stdout.close()


def filter_installable_archive(package, rules):
    """Apply .modkitignore to the generated ZIP and rebuild its embedded sums."""
    filtered = package.with_name(package.stem + '.filtered.zip')
    sums = []
    try:
        with zipfile.ZipFile(package, 'r') as source, zipfile.ZipFile(
                filtered, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            seen = set()
            for info in source.infolist():
                name = info.filename
                if name in seen:
                    raise ValueError(f'duplicate packager ZIP member: {name!r}')
                seen.add(name)
                if (info.is_dir() or name == 'SHA256SUMS.txt'
                        or ignored_path(name, rules)):
                    continue
                target = zipfile.ZipInfo(name, info.date_time)
                target.compress_type = zipfile.ZIP_DEFLATED
                target.external_attr = info.external_attr
                digest = hashlib.sha256()
                with source.open(info) as incoming, output.open(target, 'w') as outgoing:
                    while chunk := incoming.read(CHUNK):
                        digest.update(chunk)
                        outgoing.write(chunk)
                sums.append((name, digest.hexdigest()))
            sums_text = ''.join(f'{digest}  {name}\n' for name, digest in sorted(sums))
            sums_info = zipfile.ZipInfo('SHA256SUMS.txt', (2026, 9, 16, 0, 0, 0))
            sums_info.compress_type = zipfile.ZIP_DEFLATED
            sums_info.external_attr = 0o100644 << 16
            output.writestr(sums_info, sums_text.encode('utf-8'))
        filtered.replace(package)
    finally:
        if filtered.exists():
            filtered.unlink()


def run_packager(command, staging):
    process = subprocess.Popen(command, cwd=staging, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    tail = bytearray()
    try:
        while chunk := process.stderr.read(CHUNK):
            tail.extend(chunk)
            if len(tail) > 16 * 1024:
                del tail[:-16 * 1024]
        code = process.wait()
    finally:
        process.stderr.close()
    if code:
        detail = tail.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f'private packager exited with status {code}: {detail or "no diagnostics"}')


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
    rules = modkitignore_rules(source, source_sha)
    with tempfile.TemporaryDirectory(prefix='legends-package-') as directory:
        staging = Path(directory) / 'source'
        staging.mkdir()
        extract_installable_source(source, source_sha, staging, rules)
        for name in ALWAYS_EXCLUDED:
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
        run_packager([sys.executable, 'tools/package.py', '--out', str(built)], staging)
        package = built / f'stadium_realtime_combat_{version}.zip'
        filter_installable_archive(package, rules)
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
