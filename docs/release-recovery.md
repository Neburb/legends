# Recover an interrupted source release

The receiver stops on drafts, duplicate sources, damaged archives and semver tags
without releases. Recovery requires operator approval. Preserve the existing tag,
private source SHA and version; do not assign a new version or dispatch a different
source to bypass the guard.

## Prerequisites and inputs

Use Bash on Linux/WSL with Git, authenticated gh, Python 3.12 or newer, unzip and sha256sum.
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
RECIPE_DIR="$RECOVERY_DIR/recipe"
DIST_DIR="$RECOVERY_DIR/dist"
DOWNLOADED_DIR="$RECOVERY_DIR/downloaded"
ZIP_NAME="stadium_realtime_combat-${VERSION}.zip"
ZIP="$DIST_DIR/$ZIP_NAME"
SUMS="$DIST_DIR/SHA256SUMS.txt"
mkdir -p "$DIST_DIR" "$DOWNLOADED_DIR"
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

After verifying the recorded source/tag mapping, use the shared packaging script
from the **public commit checked out by the original run**. Retain the run metadata
and verify that its head SHA is the public recipe revision used in its checkout
logs (the workflow checks out its event head). Stop if those records disagree.
This pins both the script and archive validator; the private source SHA pins
`tools/package.py`. Do not substitute today's public main during recovery.
For older runs without this script, stop and obtain an explicitly approved legacy
rebuild plan based on that run's recorded steps; do not invent equivalent bytes.

```bash
gh repo clone Neburb/gen1recomp-legends "$SOURCE_DIR"
git -C "$SOURCE_DIR" fetch origin "$SOURCE_SHA"
git -C "$SOURCE_DIR" checkout --detach "$SOURCE_SHA"
test "$(git -C "$SOURCE_DIR" rev-parse HEAD)" = "$SOURCE_SHA"
gh api "repos/Neburb/legends/actions/runs/$RUN_ID" > "$RECOVERY_DIR/run.json"
RECIPE_SHA="$(python3 - "$RECOVERY_DIR/run.json" <<'PY'
import json, re, sys
run = json.load(open(sys.argv[1]))
assert run['path'] == '.github/workflows/publish.yml'
sha = run['head_sha']
assert re.fullmatch(r'[0-9a-f]{40}', sha)
print(sha)
PY
)"
# Confirm RECIPE_SHA against the retained original checkout logs before continuing.
git -C "$PUBLIC_DIR" fetch origin "$RECIPE_SHA"
git -C "$PUBLIC_DIR" worktree add --detach "$RECIPE_DIR" "$RECIPE_SHA"
test "$(git -C "$RECIPE_DIR" rev-parse HEAD)" = "$RECIPE_SHA"
# Stop if this historical recipe has no isolation boundary; never run its source tool on the host.
test -f "$RECIPE_DIR/scripts/isolated_release.py"
test -f "$RECIPE_DIR/scripts/release-container.Dockerfile"
docker build -t legends-release-builder -f "$RECIPE_DIR/scripts/release-container.Dockerfile" "$RECIPE_DIR/scripts"
python3 "$RECIPE_DIR/scripts/isolated_release.py" --source "$SOURCE_DIR" \
  --source-sha "$SOURCE_SHA" --version "$VERSION" --out "$DIST_DIR"

test -s "$ZIP" && test -s "$SUMS"
(cd "$DIST_DIR" && sha256sum -c SHA256SUMS.txt)
unzip -t "$ZIP"
python3 "$RECIPE_DIR/scripts/verify_release_archive.py" "$ZIP" "$VERSION"
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
python3 "$RECIPE_DIR/scripts/verify_release_archive.py" "$VERIFIED_DIR/$ZIP_NAME" "$VERSION"
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

An operator may retry the original dispatch only while its recorded source SHA
is still private `main`, with the original SHA and `refs/heads/main`. The pre-build
gate admits it, then the boundary validates repaired assets and skips publication.
If private `main` has advanced, preflight skips all build/boundary steps: a retry
is **not evidence** that the historical release was checked. Do not dispatch a
superseded source as a validation substitute.

For a superseded SHA use a read-only check after publication: download both assets
to another fresh directory, rerun the checksum/archive checks, compare both files
with the pinned-recipe rebuild, and compare the saved tag object. Reinspect the
release and assert the same tag, exactly one recorded Source line and published
visibility. Retain these results; this verifies assets/provenance without executing
the receiver, allocating a version, changing a release or resuming dispatch.
The metadata helper's `metadata` mode requires a hidden draft, so use the explicit
published-state check below for this read-only path:

```bash
FINAL_DIR="$(mktemp -d "$RECOVERY_DIR/final.XXXXXX")"
gh release download "$TAG" --repo Neburb/legends --dir "$FINAL_DIR"
(cd "$FINAL_DIR" && sha256sum -c SHA256SUMS.txt)
python3 "$RECIPE_DIR/scripts/verify_release_archive.py" "$FINAL_DIR/$ZIP_NAME" "$VERSION"
cmp "$ZIP" "$FINAL_DIR/$ZIP_NAME"
cmp "$SUMS" "$FINAL_DIR/SHA256SUMS.txt"
gh api "repos/Neburb/legends/git/ref/tags/$TAG" > "$RECOVERY_DIR/tag-final.json"
cmp "$RECOVERY_DIR/tag-before.json" "$RECOVERY_DIR/tag-final.json"
python3 "$PUBLIC_DIR/scripts/inspect_recovery_release.py" "$TAG" > "$RECOVERY_DIR/release-final.json"
python3 - "$RECOVERY_DIR/release-final.json" "$TAG" "$SOURCE_SHA" <<'PY'
import json, sys
release = json.load(open(sys.argv[1]))
assert release['tag_name'] == sys.argv[2] and release['draft'] is False
lines = release['body'].replace('\\n', '\n').splitlines()
sources = [line for line in lines if line.startswith('Source:')]
assert sources == ['Source: https://github.com/Neburb/gen1recomp-legends/commit/' + sys.argv[3]]
PY
```

Reconcile every orphan tag/duplicate source first. Mocked Node CI and actionlint
never publish releases, certify native installation or authorize recovery writes.

## Automated retry source proof

A healthy retry requires exactly one complete `Source:` line, exactly the expected
ZIP and `SHA256SUMS.txt` assets, valid archive checksums, and byte equality with a
rebuild of the declared immutable private commit at the existing release version.
The receiver uses its checked-out trusted public packaging recipe for this check.
If an older recipe produced different bytes, the build fails, or the commit is
unavailable, the receiver stops with the existing recovery URL; it does not
allocate another version or declare the prior release healthy. Use the original
workflow run's pinned recipe and guarded recovery steps above to investigate.
A valid ZIP and matching checksums alone do not establish source provenance.


## Isolation and archive limits

Both automatic builds and retry reconstruction execute the private packager in a
fresh Docker container as UID 65534, without network, capabilities, credentials,
host process access or the runner workspace. Only read-only source and trusted
recipe directories are mounted. `/out` is a 256 MiB tmpfs and `/tmp` a 768 MiB
tmpfs; no writable host directory is mounted. Docker logging is disabled and the
host reads at most 128 MiB plus one byte of ZIP output. A 1 GiB memory
limit, 64-process limit and 300-second host timeout bound execution. A separate
300-second watchdog in the trusted container PID 1 destroys all descendants even
if the host wrapper is killed; Docker auto-removes the exited container. SIGTERM
invokes host cleanup immediately; the host forcibly
removes the named container after success or failure before a publication step
can proceed. Host-side validation checks the output after container exit.

The archive verifier rejects sensitive path components at every depth, including
.env variants, .npmrc, .ssh, .aws/credentials and private-key suffixes. The limits
are 128 MiB compressed, 512 MiB total uncompressed, 64 MiB per ordinary member,
10,000 members and an 8 MiB central directory. Metadata has smaller caps:
4 MiB embedded checksums, 64 KiB manifest and 1 MiB main.lua. Hashing streams
64 KiB chunks and also checks CRCs. ZIP64/multi-disk archives and compression
ratios above 1000 are unsupported. Oversized published assets stop with recovery
before download (external checksum: 4 KiB). These failures require investigation;
do not bypass the limits to declare a damaged release healthy.

The manual commands build the image from the same pinned public recipe and use
its isolated wrapper for the exact source/version. Historical recipes without an
isolation boundary fail closed: stop and obtain an explicitly reviewed isolated
recovery procedure for that recipe. Never execute private tools on the operator
host or mount credential stores, the Docker socket or the operator workspace.
