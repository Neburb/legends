"""Verify the receiver's root-layout ZIP without extracting untrusted members."""
import io
import json
import re
import sys
import zipfile


def verify(archive, version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid expected release version")
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP members")
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
