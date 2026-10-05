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
read access to private repository contents and Actions. Version, duplicate release,
archive validation and isolated build requirements still apply.
