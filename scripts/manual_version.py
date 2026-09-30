"""Require an explicit source version newer than every public release tag."""
import re

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def choose_version(candidate, tags):
    if not isinstance(candidate, str) or not SEMVER.fullmatch(candidate):
        raise ValueError(f"source manifest requires an explicit X.Y.Z version: {candidate!r}")
    version = tuple(map(int, candidate.split('.')))
    released = [tuple(map(int, tag[1:].split('.'))) for tag in tags
                if tag.startswith('v') and SEMVER.fullmatch(tag[1:])]
    if released and version <= max(released):
        raise ValueError(f"source version {candidate} must exceed the latest public tag")
    return candidate
