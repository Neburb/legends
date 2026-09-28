# Recover an interrupted source release

The receiver stops on a matching draft, duplicate source, or incomplete release.
Its diagnostic links the existing release. Do not create another version, change
its source line, move its tag, or dispatch a new source to disguise a failed upload.
Recovery is a manual release publication operation requiring operator approval.

## Identify the immutable source and version

1. Open the release URL from the failed run and inspect that run's dispatch payload.
2. Record the full 40-character private source SHA, the existing public `vX.Y.Z`
   tag, release URL/ID, draft status, and public tag commit. Normalize legacy literal
   `\n` separators when reading notes. The exact `Source:` commit URL must agree
   with the original dispatch; ambiguous or duplicate source releases need manual
   investigation before proceeding.
3. Inspect assets: `gh release view "$TAG" --repo Neburb/legends --json tagName,isDraft,body,assets,url`.
   Download to a fresh directory: `gh release download "$TAG" --repo Neburb/legends --dir "$RECOVERY_DIR"`.

## Rebuild and verify

1. In an isolated checkout, fetch and check out the recorded private SHA, verify
   `git rev-parse HEAD`, and use the **Build installable public ZIP** procedure in
   `.github/workflows/publish.yml`. Supply the recorded SHA as `SOURCE_SHA` and
   the existing tag without `v` as `VERSION`; do not run the version allocator.
   Archive that commit, remove the same development metadata, stamp manifest and
   `mod.exports.version`, then run `tools/package.py` exactly as the workflow does.
2. Preserve `stadium_realtime_combat-X.Y.Z.zip` and regenerate `SHA256SUMS.txt`
   with `sha256sum` in the asset directory. Both files must be nonempty. Run
   `sha256sum -c SHA256SUMS.txt` and `unzip -t stadium_realtime_combat-X.Y.Z.zip`.
   Inspect the packaged manifest and main.lua version; confirm the public repo
   field and existing release version. The checksum must contain one SHA-256 line
   for this exact ZIP, with no path prefix or other asset.
3. Compare with downloaded assets and investigate unexpected differences.
   Retain the source SHA, rebuild commands, hashes and validation output as evidence.

## Repair the existing release and retry

1. With operator approval, upload verified replacement assets to the **existing**
   release: `gh release upload "$TAG" "$ZIP" "$SUMS" --clobber --repo Neburb/legends`.
   Do not delete/recreate the tag or relabel the source.
2. Download those uploaded assets again into a fresh directory and repeat checksum,
   ZIP and version checks. Recheck the release notes' exact immutable source line.
3. If the original run left a matching draft, finish that same release only after
   the uploaded assets validate and publication is explicitly approved:
   `gh release edit "$TAG" --draft=false --repo Neburb/legends`.
   A draft must never be treated as successful publication or bypassed with a new tag.
4. Retry the original dispatch with its original source SHA and `refs/heads/main`.
   The boundary verifies the repaired published assets and skips publication,
   without creating another published version. A stale source cannot create a fresh
   release. If multiple releases claim the same source, resolve that ambiguity
   manually before retrying; automatic recovery does not delete releases or pick
   a winner.

PR/push CI runs `node --test tests/release_boundary.test.cjs` and actionlint. These
mocked tests never publish releases; they do not replace asset inspection or
authorize manual publication.
