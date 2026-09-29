"""Verify the receiver's root-layout ZIP without extracting untrusted members."""
import hashlib
import stat
import pathlib
import io
import json
import re
import sys
import zipfile


# Match the mod ZIP produced by tools/package.py: regular files at root paths,
# excluding source caches, credentials and binary/runtime artifacts.
BLOCKED_PARTS = {'.git', '.github', '.codex-remote-attachments', '__pycache__', 'dist', '.cache', '.pytest_cache', 'baseroms', 'cache', 'derived'}
BLOCKED_SUFFIXES = {'.z64', '.n64', '.v64', '.rom', '.gb', '.gbc', '.exe', '.dll', '.so', '.ttf', '.otf', '.ttc', '.woff', '.woff2', '.eot', '.fon', '.zip', '.love', '.pyc', '.rtcbin', '.sav', '.srm', '.state', '.gba', '.bin', '.pack'}


def safe_member(member):
    name = member.filename
    parts = name.split('/')
    mode = member.external_attr >> 16
    if (not name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name)
            or any(p in ('', '.', '..') or p in BLOCKED_PARTS for p in parts)
            or member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
            or parts[-1].startswith('.env') or '.tmp.' in parts[-1]
            or pathlib.PurePosixPath(name).suffix.lower() in BLOCKED_SUFFIXES
            or name.startswith('reports/animation_lab/')):
        raise ValueError('unsafe or excluded ZIP member: ' + repr(name))


def verify_checksums(package, names):
    entries = {}
    for line in package.read('SHA256SUMS.txt').decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match or match[2] in entries:
            raise ValueError('malformed or duplicate embedded checksum')
        entries[match[2]] = match[1]
    if set(entries) != set(names) - {'SHA256SUMS.txt'}:
        raise ValueError('embedded checksum coverage mismatch')
    for name, digest in entries.items():
        if hashlib.sha256(package.read(name)).hexdigest() != digest:
            raise ValueError('embedded checksum mismatch: ' + name)


def verify(archive, version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid expected release version")
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP members")
        for member in package.infolist():
            safe_member(member)
        verify_checksums(package, names)
        if package.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        manifest = json.loads(package.read("manifest.json"))
        if not isinstance(manifest, dict) or (
            manifest.get("id") != "stadium_realtime_combat"
            or manifest.get("entry") != "main.lua"
            or manifest.get("version") != version
            or manifest.get("github") != "Neburb/legends"
        ):
            raise ValueError("manifest identity, entry, version or public repository mismatch")
        main = package.read("main.lua").decode("utf-8")
        versions = re.findall(r'mod\.exports\.version\s*=\s*"([^"\r\n]+)"', main)
        if versions != [version]:
            raise ValueError("main.lua release version mismatch or ambiguous declaration")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: verify_release_archive.py ZIP|- X.Y.Z")
    try:
        archive = io.BytesIO(sys.stdin.buffer.read()) if sys.argv[1] == "-" else sys.argv[1]
        verify(archive, sys.argv[2])
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
        raise SystemExit(f"Release archive verification failed: {error}")
