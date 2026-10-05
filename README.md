# legends

Public release packages are built from manually versioned commits in
`Neburb/gen1recomp-legends`, using the isolated packaging workflow.

Ordinary `publish-legends` dispatches require the source SHA to remain current
private `main` before building and before publishing. When publishing an explicitly
approved snapshot while development continues, set `allow_main_ancestor: true`
in `client_payload`, alongside `source_repo`, the full `source_sha` and
`source_ref: "refs/heads/main"`.

This opt-in requires the snapshot to be an ancestor of current main and its latest
push CI run on main for that exact SHA to have completed successfully. Both checks
run before executing source and again before publication. The source token needs
read access to private repository contents. Actions read access enables live CI
checks. For a contents-only token, an operator can instead record the exact-source
successful CI run in trusted `scripts/approved_source.json` with an expiration,
after independently verifying it through authenticated GitHub access. A 403 may
use only that recorded SHA before expiration; dispatch payloads cannot supply an
approval, and other API failures stop publication. Version, duplicate release,
archive validation and isolated build requirements still apply.
