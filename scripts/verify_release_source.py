"""Validate downloaded ZIP bytes against a rebuild of the declared private commit.

Uses the trusted recipe checked out for this receiver run. An older/incompatible
recipe or any byte mismatch fails closed to documented pinned-recipe recovery.
No release, tag or asset writes occur here.
"""
import argparse
from pathlib import Path
import sys
import tempfile

from package_release import build
from verify_release_archive import verify, read_bounded, MAX_ARCHIVE


def verify_source(data, source, source_sha, version):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('compressed ZIP exceeds size limit')
    with tempfile.TemporaryDirectory(prefix='legends-source-proof-') as directory:
        root = Path(directory)
        downloaded = root / 'downloaded.zip'
        downloaded.write_bytes(data)
        verify(downloaded, version)
        rebuilt = build(source, source_sha, version, root / 'rebuilt')
        if data != rebuilt.read_bytes():
            raise ValueError('release ZIP differs from the declared source rebuild')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    verify_source(read_bounded(sys.stdin.buffer, MAX_ARCHIVE), args.source, args.source_sha, args.version)
