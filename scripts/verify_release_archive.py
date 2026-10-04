"""Verify the receiver's root-layout ZIP without extracting untrusted members."""
import hashlib
import stat
import pathlib
import io
import json
import re
import sys
import zipfile
import struct


# Match the mod ZIP produced by tools/package.py: regular files at root paths,
# excluding source caches, credentials and binary/runtime artifacts.
BLOCKED_PARTS = {'.git', '.github', '.codex-remote-attachments', '__pycache__', 'dist', '.cache', '.pytest_cache', 'baseroms', 'cache', 'derived'}
SENSITIVE_PARTS = {'.npmrc', '.pypirc', '.netrc', '_netrc', '.ssh', '.aws', '.azure', '.config', '.docker', '.kube', '.gnupg', 'credentials', 'credentials.json', 'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'authorized_keys'}
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
MAX_MEMBERS = 10000
METADATA_LIMITS = {'SHA256SUMS.txt': 4 * 1024 * 1024, 'manifest.json': 64 * 1024, 'main.lua': 1024 * 1024}
CHUNK = 64 * 1024


def read_bounded(stream, limit):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('release input exceeds size limit')
    return data


BLOCKED_SUFFIXES = {'.z64', '.n64', '.v64', '.rom', '.gb', '.gbc', '.exe', '.dll', '.so', '.ttf', '.otf', '.ttc', '.woff', '.woff2', '.eot', '.fon', '.zip', '.love', '.pyc', '.rtcbin', '.sav', '.srm', '.state', '.gba', '.bin', '.pack'}


PAINTER_FONT_MEMBERS = {
    'assets/painter/RobotoCondensed.ttf',
    'assets/painter/RobotoCondensed-Italic.ttf',
    'assets/painter/Caveat.ttf',
}


def safe_member(member):
    name = member.filename
    parts = name.split('/')
    mode = member.external_attr >> 16
    if (not name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name)
            or any(p in ('', '.', '..') or p.lower() in BLOCKED_PARTS or p.lower() in SENSITIVE_PARTS or p.lower().startswith('.env') for p in parts)
            or member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
            or '.tmp.' in parts[-1] or pathlib.PurePosixPath(name).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}
            or (pathlib.PurePosixPath(name).suffix.lower() in BLOCKED_SUFFIXES
                and name not in PAINTER_FONT_MEMBERS)
            or name.startswith('reports/animation_lab/')):
        raise ValueError('unsafe or excluded ZIP member: ' + repr(name))


def verify_checksums(package, names):
    entries = {}
    for line in metadata(package, 'SHA256SUMS.txt').decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match or match[2] in entries:
            raise ValueError('malformed or duplicate embedded checksum')
        entries[match[2]] = match[1]
    if set(entries) != set(names) - {'SHA256SUMS.txt'}:
        raise ValueError('embedded checksum coverage mismatch')
    for name, digest in entries.items():
        hashed = hashlib.sha256()
        consumed = 0
        with package.open(name) as member:
            while chunk := member.read(CHUNK):
                consumed += len(chunk)
                if consumed > MAX_MEMBER:
                    raise ValueError('ZIP member exceeds size limit')
                hashed.update(chunk)
        if hashed.hexdigest() != digest:
            raise ValueError('embedded checksum mismatch: ' + name)


def metadata(package, name):
    with package.open(name) as member:
        return read_bounded(member, METADATA_LIMITS[name])


def verify(archive, version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid expected release version")
    stream = archive if hasattr(archive, 'seek') else open(archive, 'rb')
    try:
        stream.seek(0, 2); size = stream.tell()
        if size > MAX_ARCHIVE:
            raise ValueError('compressed ZIP exceeds size limit')
        # Bound central-directory parsing before ZipFile allocates member objects.
        stream.seek(max(0, size - 65557)); tail = stream.read(65557)
        position = tail.rfind(b'PK\x05\x06')
        record = tail[position:] if position >= 0 else b''
        if len(record) < 22:
            raise ValueError('missing ZIP end record')
        _, disk, directory_disk, disk_count, count, directory_size, offset, comment = struct.unpack('<4s4H2LH', record[:22])
        if (tail[max(0, position - 20):position - 16] == b'PK\x06\x07'
                or disk or directory_disk or disk_count != count or count > MAX_MEMBERS
                or directory_size > 8 * 1024 * 1024 or offset + directory_size > size
                or len(record) != 22 + comment):
            raise ValueError('ZIP central directory exceeds limits or is unsupported')
        stream.seek(0)
    finally:
        if stream is not archive:
            stream.close()
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) > MAX_MEMBERS:
            raise ValueError('too many ZIP members')
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP members")
        total = 0
        for member in package.infolist():
            safe_member(member)
            total += member.file_size
            limit = METADATA_LIMITS.get(member.filename, MAX_MEMBER)
            if member.file_size > limit or total > MAX_TOTAL:
                raise ValueError('uncompressed ZIP exceeds size limit')
            if member.file_size > max(1, member.compress_size) * 1000:
                raise ValueError('ZIP compression ratio exceeds limit')
        verify_checksums(package, names)
        manifest = json.loads(metadata(package, "manifest.json"))
        if not isinstance(manifest, dict) or (
            manifest.get("id") != "stadium_realtime_combat"
            or manifest.get("entry") != "main.lua"
            or manifest.get("version") != version
            or manifest.get("github") != "Neburb/legends"
        ):
            raise ValueError("manifest identity, entry, version or public repository mismatch")
        main = metadata(package, "main.lua").decode("utf-8")
        versions = re.findall(r'mod\.exports\.version\s*=\s*"([^"\r\n]+)"', main)
        if versions != [version]:
            raise ValueError("main.lua release version mismatch or ambiguous declaration")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: verify_release_archive.py ZIP|- X.Y.Z")
    try:
        archive = io.BytesIO(read_bounded(sys.stdin.buffer, MAX_ARCHIVE)) if sys.argv[1] == "-" else sys.argv[1]
        verify(archive, sys.argv[2])
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
        raise SystemExit(f"Release archive verification failed: {error}")
