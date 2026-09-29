"""Run source-owned packaging only in a credential-free, disposable container.

The host validates output after container exit; source descendants die with it.
Only source and the trusted recipe are mounted; output stays in bounded tmpfs.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import uuid
import subprocess
import sys
import threading
import io
import signal

from verify_release_archive import verify, read_bounded, MAX_ARCHIVE

IMAGE = 'legends-release-builder'


def container_command(source, source_sha, version, name):
    recipe = Path(__file__).resolve().parent
    return ['docker', 'run', '--rm', '--name', name, '--network=none', '--read-only',
            '--user=65534:65534', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=64', '--memory=1g', '--cpus=2',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=768m',
            '--tmpfs=/out:rw,nosuid,noexec,size=256m,mode=1777', '--log-driver=none',
            '--mount', f'type=bind,source={Path(source).resolve()},target=/source,readonly',
            '--mount', f'type=bind,source={recipe},target=/recipe,readonly',
            IMAGE, 'python3', '/recipe/container_release.py', '--source', '/source',
            '--source-sha', source_sha, '--version', version, '--out', '/out']


def isolated_build(source, source_sha, version, out, downloaded=None):
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('invalid immutable source or version')
    # Reject damaged/oversized downloads before executing any source-owned code.
    if downloaded is not None:
        if len(downloaded) > MAX_ARCHIVE:
            raise ValueError('compressed ZIP exceeds size limit')
        verify(io.BytesIO(downloaded), version)
    environment = {k: os.environ[k] for k in ('PATH', 'SystemRoot', 'TEMP', 'TMP') if k in os.environ}
    name = 'legends-package-' + uuid.uuid4().hex
    command = container_command(source, source_sha, version, name)
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    expired = threading.Event()
    def timeout():
        if process.poll() is None:
            expired.set(); process.kill()
    timer = threading.Timer(300, timeout); timer.start()
    try:
        # Source cannot write to a host filesystem or an unbounded Docker log.
        data = read_bounded(process.stdout, MAX_ARCHIVE)
        code = process.wait()
        if expired.is_set():
            raise subprocess.TimeoutExpired(command, 300)
        if code:
            raise subprocess.CalledProcessError(code, command)
    finally:
        timer.cancel()
        # A killed CLI does not stop its container; drain it on every exit path.
        try:
            drain = subprocess.run(['docker', 'rm', '--force', name], env=environment,
                                   timeout=30, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True)
            # --rm may already have removed a normally exited container.
            if drain.returncode and 'No such container:' not in drain.stderr:
                raise subprocess.CalledProcessError(drain.returncode, drain.args)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=30); process.stdout.close(); timer.join()
    verify(io.BytesIO(data), version)
    if downloaded is not None:
        if data != downloaded:
            raise ValueError('release ZIP differs from the declared source rebuild')
    else:
        destination = Path(out); destination.mkdir(parents=True, exist_ok=True)
        name = f'stadium_realtime_combat-{version}.zip'
        (destination / name).write_bytes(data)
        (destination / 'SHA256SUMS.txt').write_text(
            f'{hashlib.sha256(data).hexdigest()}  {name}\n', encoding='utf-8', newline='\n')


def cancel(signum, frame):
    raise SystemExit(128 + signum)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, cancel)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path, default=Path('dist'))
    parser.add_argument('--verify-stdin', action='store_true')
    args = parser.parse_args()
    data = read_bounded(sys.stdin.buffer, MAX_ARCHIVE) if args.verify_stdin else None
    isolated_build(args.source, args.source_sha, args.version, args.out, data)
