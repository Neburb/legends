# Recover an interrupted source release

The receiver stops on drafts, duplicate sources, damaged archives and semver tags
without releases. Recovery requires operator approval. Preserve the existing tag,
private source SHA and version; do not invoke the allocator or dispatch a different
source to bypass the guard.

## Prerequisites and inputs

Use Bash on Linux/WSL with Git, authenticated gh, Python 3, tar, unzip and sha256sum.
You need private source access, and write access for manual publication. Start in
a Neburb/legends checkout containing scripts/verify_release_archive.py.
Read the failed run's dispatch payload and release notes. Record the existing tag,
full private source SHA, original run ID, draft status and public tag commit. The
public tag commit is not the private source SHA. Normalize legacy literal `\n`
separators when inspecting notes. The exact Source URL must agree with the payload.
For orphan tags, establish source provenance from the original dispatch/logs; stop
if ambiguous. Reconcile duplicate source releases manually before proceeding.

```bash
set -euo pipefail
PUBLIC_DIR="$PWD"
test -f "$PUBLIC_DIR/scripts/verify_release_archive.py"
read -r -p 'Existing public tag (vX.Y.Z): ' TAG
read -r -p 'Recorded private source SHA (40 hex): ' SOURCE_SHA
read -r -p 'Original public workflow run ID: ' RUN_ID
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$RUN_ID" =~ ^[0-9]+$ ]]
VERSION="${TAG#v}"
RECOVERY_DIR="$(mktemp -d)"
SOURCE_DIR="$RECOVERY_DIR/source"
STAGING_DIR="$RECOVERY_DIR/package"
DIST_DIR="$RECOVERY_DIR/dist"
DOWNLOADED_DIR="$RECOVERY_DIR/downloaded"
ZIP_NAME="stadium_realtime_combat-${VERSION}.zip"
ZIP="$DIST_DIR/$ZIP_NAME"
SUMS="$DIST_DIR/SHA256SUMS.txt"
mkdir -p "$STAGING_DIR" "$DIST_DIR" "$DOWNLOADED_DIR"
gh api "repos/Neburb/legends/git/ref/tags/$TAG" > "$RECOVERY_DIR/tag-before.json"
gh run view "$RUN_ID" --repo Neburb/legends --log > "$RECOVERY_DIR/original-run.log"
gh release view "$TAG" --repo Neburb/legends --json tagName,isDraft,body,assets,url
```

For an orphan, the last command reports release not found: retain the tag record
and establish provenance before any write. For an existing release, download its
assets separately: `gh release download "$TAG" --repo Neburb/legends --dir "$DOWNLOADED_DIR"`.

## Rebuild the existing version, without allocating one

After verifying the recorded source/tag mapping, run the workflow's same archive,
stamp and package steps in an isolated directory:

```bash
gh repo clone Neburb/gen1recomp-legends "$SOURCE_DIR"
git -C "$SOURCE_DIR" fetch origin "$SOURCE_SHA"
git -C "$SOURCE_DIR" checkout --detach "$SOURCE_SHA"
test "$(git -C "$SOURCE_DIR" rev-parse HEAD)" = "$SOURCE_SHA"
git -C "$SOURCE_DIR" archive "$SOURCE_SHA" | tar -x -C "$STAGING_DIR"
python3 - "$STAGING_DIR" "$VERSION" <<'PY'
import json, pathlib, re, shutil, sys
root = pathlib.Path(sys.argv[1]).resolve()
version = sys.argv[2]
for name in ('.github', '.git', '.gitattributes', '.gitignore', '.luarc.json'):
    target = root / name
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
manifest_path = root / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
manifest['version'] = version
manifest['github'] = 'Neburb/legends'
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
main_path = root / 'main.lua'
source, count = re.subn(r'(mod\.exports\.version\s*=\s*")[^"]+(\")',
                      rf'\g<1>{version}\g<2>', main_path.read_text(encoding='utf-8'), count=1)
if count != 1:
    raise SystemExit('main.lua mod version declaration not found')
main_path.write_text(source, encoding='utf-8')
PY
(cd "$STAGING_DIR" && python3 tools/package.py --out "$DIST_DIR")
test -s "$DIST_DIR/stadium_realtime_combat_${VERSION}.zip"
mv "$DIST_DIR/stadium_realtime_combat_${VERSION}.zip" "$ZIP"
(cd "$DIST_DIR" && sha256sum "$ZIP_NAME" > SHA256SUMS.txt)
test -s "$ZIP" && test -s "$SUMS"
(cd "$DIST_DIR" && sha256sum -c SHA256SUMS.txt)
unzip -t "$ZIP"
python3 "$PUBLIC_DIR/scripts/verify_release_archive.py" "$ZIP" "$VERSION"
```

The validator checks CRCs, unique members, root manifest/main, package identity,
public repository and both embedded versions. The checksum must be one line for
ZIP_NAME without a path prefix. Compare downloaded assets against the rebuild and
investigate differences. Retain commands, hashes and validation output as evidence.

## Manual repair after operator approval

For an existing release, replace its assets without recreating its tag:

```bash
gh release upload "$TAG" "$ZIP" "$SUMS" --clobber --repo Neburb/legends
```

For a proven orphan only, create a draft on its existing tag. `--verify-tag`
prevents creating a tag, and the notes retain the recorded private source:

```bash
printf 'Recovered package for private source commit %s.\n\nSource: https://github.com/Neburb/gen1recomp-legends/commit/%s\n' \
  "$SOURCE_SHA" "$SOURCE_SHA" > "$RECOVERY_DIR/notes.md"
gh release create "$TAG" --verify-tag --draft --repo Neburb/legends \
  --title "Legends $VERSION" --notes-file "$RECOVERY_DIR/notes.md" "$ZIP" "$SUMS"
```

Download to a fresh directory and verify the actual replacements, tag object and
exact source line before approving publication:

```bash
VERIFIED_DIR="$(mktemp -d "$RECOVERY_DIR/verified.XXXXXX")"
gh release download "$TAG" --repo Neburb/legends --dir "$VERIFIED_DIR"
(cd "$VERIFIED_DIR" && sha256sum -c SHA256SUMS.txt)
unzip -t "$VERIFIED_DIR/$ZIP_NAME"
python3 "$PUBLIC_DIR/scripts/verify_release_archive.py" "$VERIFIED_DIR/$ZIP_NAME" "$VERSION"
gh api "repos/Neburb/legends/git/ref/tags/$TAG" > "$RECOVERY_DIR/tag-after.json"
cmp "$RECOVERY_DIR/tag-before.json" "$RECOVERY_DIR/tag-after.json"
gh release view "$TAG" --repo Neburb/legends --json tagName,isDraft,body,assets,url
```

Finish the same draft only after these checks and explicit publication approval:

```bash
gh release edit "$TAG" --draft=false --repo Neburb/legends
```

An operator may then retry the original dispatch with its original SHA and
refs/heads/main. The boundary validates the repaired assets and skips publication.
Reconcile every orphan tag/duplicate source first. Mocked Node CI and actionlint
never publish releases, certify native installation or authorize recovery writes.
