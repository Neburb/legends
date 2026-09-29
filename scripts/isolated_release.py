"""Run source-owned packaging only in a credential-free, disposable container.

The host validates output after container exit; source descendants die with it.
Only source, the trusted recipe and an empty output directory are mounted.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import uuid
import subprocess
import sys
import tempfile

from verify_release_archive import verify, read_bounded, MAX_ARCHIVE

IMAGE = 'legends-release-builder'


def container_command(source, out, source_sha, version, name):
    recipe = Path(__file__).resolve().parent
    return ['docker', 'run', '--name', name, '--network=none', '--read-only',
            '--user=65534:65534', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=64', '--memory=1g', '--cpus=2',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=768m',
            '--mount', f'type=bind,source={Path(source).resolve()},target=/source,readonly',
            '--mount', f'type=bind,source={recipe},target=/recipe,readonly',
            '--mount', f'type=bind,source={Path(out).resolve()},target=/out',
            IMAGE, 'python3', '/recipe/package_release.py', '--source', '/source',
            '--source-sha', source_sha, '--version', version, '--out', '/out']


def isolated_build(source, source_sha, version, out, downloaded=None):
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('invalid immutable source or version')
    # Reject damaged/oversized downloads before executing any source-owned code.
    if downloaded is not None:
        if len(downloaded) > MAX_ARCHIVE:
            raise ValueError('compressed ZIP exceeds size limit')
        import io
        verify(io.BytesIO(downloaded), version)
    with tempfile.TemporaryDirectory(prefix='legends-isolated-') as directory:
        output = Path(directory) / 'output'; output.mkdir()
        # Runner directories are otherwise inaccessible to the unprivileged UID.
        Path(directory).chmod(0o755); output.chmod(0o777)
        environment = {k: os.environ[k] for k in ('PATH', 'SystemRoot', 'TEMP', 'TMP') if k in os.environ}
        name = 'legends-package-' + uuid.uuid4().hex
        try:
            subprocess.run(container_command(source, output, source_sha, version, name),
                           env=environment, check=True, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            # Timeout kills the CLI, not the container. Drain it before any next step.
            subprocess.run(['docker', 'rm', '--force', name], env=environment,
                           check=True, timeout=30, stdout=subprocess.DEVNULL)
        package = output / f'stadium_realtime_combat-{version}.zip'
        if package.is_symlink() or not package.is_file():
            raise ValueError('container did not return a regular ZIP')
        verify(package, version)
        with package.open('rb') as stream:
            data = read_bounded(stream, MAX_ARCHIVE)
        if downloaded is not None:
            if data != downloaded:
                raise ValueError('release ZIP differs from the declared source rebuild')
        else:
            destination = Path(out); destination.mkdir(parents=True, exist_ok=True)
            name = package.name
            (destination / name).write_bytes(data)
            (destination / 'SHA256SUMS.txt').write_text(
                f'{hashlib.sha256(data).hexdigest()}  {name}\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path, default=Path('dist'))
    parser.add_argument('--verify-stdin', action='store_true')
    args = parser.parse_args()
    data = read_bounded(sys.stdin.buffer, MAX_ARCHIVE) if args.verify_stdin else None
    isolated_build(args.source, args.source_sha, args.version, args.out, data)
