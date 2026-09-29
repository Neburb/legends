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
ASSET_COUNT="$(python3 - "$RECOVERY_DIR/release-before.json" <<'PY'
import json, sys
release = json.load(open(sys.argv[1]))
print(len(release['assets']) if release else 0)
PY
)"
if [ "$ASSET_COUNT" -gt 0 ]; then
  gh release download "$TAG" --repo Neburb/legends --dir "$DOWNLOADED_DIR"
fi
```

The inspection helper confirms authenticated repository access and treats only an
HTTP 404 from the release endpoint as an orphan. Authentication, permission,
network and other API errors stop the sequence. The tag lookup above must succeed.
For an orphan retain the tag record and prove provenance before any write. Original
assets of an existing release are backed up in DOWNLOADED_DIR before repair.
A zero-asset draft has an intentionally empty backup; no download is attempted.

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

## Pause and drain the publisher after operator approval

Manual CLI commands do not participate in the workflow's `publish-legends`
concurrency group. Pause the private dispatch producer and any manual dispatch
sources; record payloads arriving during maintenance for later reconciliation.
With separate operator approval to disable the public receiver, run:

```bash
gh workflow disable publish.yml --repo Neburb/legends
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" quiescent
```

Disabling prevents new receiver runs; it does not stop runs already queued or in
progress. If the guard fails, inspect all receiver runs, wait for them to complete
(or cancel them with operator approval and wait for completion), then repeat the
guard. It checks every page and rejects every non-completed status, including
queued/waiting/pending runs. Do not perform any release write until it succeeds.
Keep the workflow disabled and dispatch sources paused throughout repair,
rollback, verification and final publication. A failed step keeps maintenance
active. The gates below check this again immediately before each write sequence.

## Manual repair after operator approval

Use a maintenance window for an existing published release: notify consumers and
pause update/download jobs, record its original visibility and retain every original
asset (including damaged ones) and release metadata. Direct cached download URLs
may outlive hiding; do not promise atomic updates. Keep consumers paused until the
replacement or rollback has been verified. This sequence first hides the same
release as a draft, verifies that state, and then uploads. If hiding is rejected or
the API still reports published, stop without replacing assets.

```bash
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" quiescent
if [ "$RELEASE_KIND" = published ]; then
  gh release edit "$TAG" --draft=true --repo Neburb/legends
fi
if [ "$RELEASE_KIND" != orphan ]; then
  python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/hidden.json"
  python3 - "$RECOVERY_DIR/hidden.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['draft'], 'release must be hidden before repair'
PY
  python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" metadata "$RECOVERY_DIR/hidden.json" "$TAG" "$SOURCE_SHA"
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
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" quiescent
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
if [ "${#ORIGINAL_ASSETS[@]}" -gt 0 ]; then
  gh release upload "$TAG" "${ORIGINAL_ASSETS[@]}" --clobber --repo Neburb/legends
fi
ROLLBACK_DIR="$(mktemp -d "$RECOVERY_DIR/rollback.XXXXXX")"
if [ "${#ORIGINAL_ASSETS[@]}" -gt 0 ]; then
  gh release download "$TAG" --repo Neburb/legends --dir "$ROLLBACK_DIR"
else
  python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/rollback-empty.json"
  python3 - "$RECOVERY_DIR/rollback-empty.json" <<'PY'
import json, sys
release = json.load(open(sys.argv[1]))
assert release['draft'] and release['assets'] == [], 'empty original set must remain hidden and empty'
PY
fi
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
notes/title/tag. If the metadata gate reports a tag or Source mismatch, stop:
retain the snapshot and reconcile it with the original dispatch/logs. Never
change the recorded source to make the gate pass. A separately approved metadata
correction may edit notes on this same hidden release using an audited notes file
(`gh release edit "$TAG" --notes-file "$RECOVERY_DIR/approved-notes.md" --repo
Neburb/legends`), with the publisher drained/disabled. Preserve unrelated notes.
For a tag mismatch, investigate and obtain an explicit correction plan; do not
move or replace tags as part of this procedure. Reinspect and rerun the metadata
gate after any approved correction. This is additional repair authorization,
not implied by an asset upload approval.

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
cmp "$ZIP" "$VERIFIED_DIR/$ZIP_NAME"
cmp "$SUMS" "$VERIFIED_DIR/SHA256SUMS.txt"
python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/release-verified.json"
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" metadata "$RECOVERY_DIR/release-verified.json" "$TAG" "$SOURCE_SHA"
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" quiescent
```

The comparisons require the uploaded bytes and checksum file to match the
package rebuilt from the recorded source. A same-version, self-consistent package
from another source fails this gate. Nonreproducible bytes also stop publication:
investigate the build inputs and archive metadata, record hashes and differences,
and obtain explicit approval for a revised verification plan before proceeding.
Do not silently bypass `cmp` or equate internal consistency with source provenance.
The metadata gate asserts the API's `tag_name` (the CLI's `tagName`) and exactly
one full Source line, normalizing legacy literal `\n` separators.

Finish the same draft only after these checks and explicit publication approval:

```bash
python3 "$PUBLIC_DIR/scripts/verify_recovery_state.py" quiescent
gh release edit "$TAG" --draft=false --repo Neburb/legends
```

Reinspect the published release and retain the final tag/source/assets evidence.
Reconcile interrupted runs and all dispatch payloads recorded during maintenance;
do not replay unknown or stale sources. With operator approval, enable the
receiver (`gh workflow enable publish.yml --repo Neburb/legends`) and resume the
private producer/manual dispatch sources and consumers. Reconcile dispatches lost
while the receiver was disabled before declaring maintenance complete.

An operator may then retry the original dispatch with its original SHA and
refs/heads/main. The boundary validates the repaired assets and skips publication.
Reconcile every orphan tag/duplicate source first. Mocked Node CI and actionlint
never publish releases, certify native installation or authorize recovery writes.
