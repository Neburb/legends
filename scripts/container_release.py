"""Trusted container entry: package on tmpfs, then return only bounded ZIP bytes."""
import argparse
from pathlib import Path
import sys
import os
import threading
from package_release import build
from verify_release_archive import read_bounded, MAX_ARCHIVE

# Runs as namespace PID 1: exiting destroys every source-owned descendant,
# even when the authenticated host wrapper or Docker CLI has been SIGKILLed.
LIFETIME_SECONDS = 300


def expire():
    os._exit(124)


if __name__ == '__main__':
    watchdog = threading.Timer(LIFETIME_SECONDS, expire)
    watchdog.daemon = True
    watchdog.start()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    package = build(args.source, args.source_sha, args.version, args.out)
    if package.is_symlink() or not package.is_file():
        raise ValueError('container did not return a regular ZIP')
    with package.open('rb') as stream:
        sys.stdout.buffer.write(read_bounded(stream, MAX_ARCHIVE))
