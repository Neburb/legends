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
python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/release-before.json"
RELEASE_KIND="$(python3 - "$RECOVERY_DIR/release-before.json" <<'PY'
import json, sys
release = json.load(open(sys.argv[1]))
print('orphan' if release is None else 'draft' if release['draft'] else 'published')
PY
)"
printf 'Recovery branch: %s\n' "$RELEASE_KIND"
if [ "$RELEASE_KIND" != orphan ]; then
  gh release download "$TAG" --repo Neburb/legends --dir "$DOWNLOADED_DIR"
fi
```

The inspection helper confirms authenticated repository access and treats only an
HTTP 404 from the release endpoint as an orphan. Authentication, permission,
network and other API errors stop the sequence. The tag lookup above must succeed.
For an orphan retain the tag record and prove provenance before any write. Original
assets of an existing release are backed up in DOWNLOADED_DIR before repair.

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

The validator checks CRCs, regular safe member paths and package exclusions,
complete internal SHA256SUMS coverage and every member digest, root manifest/main,
package identity, public repository and both embedded versions. The checksum must be one line for
ZIP_NAME without a path prefix. Compare downloaded assets against the rebuild and
investigate differences. Retain commands, hashes and validation output as evidence.

## Manual repair after operator approval

Use a maintenance window for an existing published release: notify consumers and
pause update/download jobs, record its original visibility and retain every original
asset (including damaged ones) and release metadata. Direct cached download URLs
may outlive hiding; do not promise atomic updates. Keep consumers paused until the
replacement or rollback has been verified. This sequence first hides the same
release as a draft, verifies that state, and then uploads. If hiding is rejected or
the API still reports published, stop without replacing assets.

```bash
if [ "$RELEASE_KIND" = published ]; then
  gh release edit "$TAG" --draft=true --repo Neburb/legends
fi
if [ "$RELEASE_KIND" != orphan ]; then
  python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/hidden.json"
  python3 - "$RECOVERY_DIR/hidden.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['draft'], 'release must be hidden before repair'
PY
  gh release upload "$TAG" "$ZIP" "$SUMS" --clobber --repo Neburb/legends
else
  printf 'Recovered package for private source commit %s.\n\nSource: https://github.com/Neburb/gen1recomp-legends/commit/%s\n' \
    "$SOURCE_SHA" "$SOURCE_SHA" > "$RECOVERY_DIR/notes.md"
  gh release create "$TAG" --verify-tag --draft --repo Neburb/legends \
    --title "Legends $VERSION" --notes-file "$RECOVERY_DIR/notes.md" "$ZIP" "$SUMS"
fi
```

The orphan branch reuses the proven tag and never creates or moves a tag. For an
upload interruption or verification failure, **leave the release hidden** and the
maintenance window active. Restore the saved original assets to the same draft;
retry this recovery block after an interrupted upload:

```bash
# Existing releases only. Do not run for a newly created orphan draft.
test "$RELEASE_KIND" != orphan
python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/hidden.json"
python3 - "$RECOVERY_DIR/hidden.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['draft']
PY
# Remove only newly introduced asset names before restoring the saved originals.
python3 - "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" "$DOWNLOADED_DIR" <<'PY'
import json, pathlib, subprocess, sys
helper, tag, backup = sys.argv[1:]
release = json.loads(subprocess.check_output(['python3', helper, tag], text=True))
assert release['draft']
saved = {p.name for p in pathlib.Path(backup).iterdir()}
for asset in release['assets']:
    if asset['name'] not in saved:
        subprocess.run(['gh', 'release', 'delete-asset', tag, asset['name'], '--yes',
                        '--repo', 'Neburb/legends'], check=True)
PY
shopt -s nullglob
ORIGINAL_ASSETS=("$DOWNLOADED_DIR"/*)
test "${#ORIGINAL_ASSETS[@]}" -gt 0
gh release upload "$TAG" "${ORIGINAL_ASSETS[@]}" --clobber --repo Neburb/legends
ROLLBACK_DIR="$(mktemp -d "$RECOVERY_DIR/rollback.XXXXXX")"
gh release download "$TAG" --repo Neburb/legends --dir "$ROLLBACK_DIR"
python3 - "$DOWNLOADED_DIR" "$ROLLBACK_DIR" <<'PY'
import pathlib, sys
before, after = map(pathlib.Path, sys.argv[1:])
assert {p.name for p in before.iterdir()} == {p.name for p in after.iterdir()}
assert all(p.read_bytes() == (after / p.name).read_bytes() for p in before.iterdir())
PY
```

For an orphan draft, retain the draft for a verified retry instead of exposing it.
Rollback proves restoration, not health: if originals were damaged or incomplete,
keep the release hidden and rebuild again. Only restore visibility after the full
health checks below succeed and an operator approves publication. Preserve original
notes/title/tag; do not replace notes on the existing-release branch.

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
