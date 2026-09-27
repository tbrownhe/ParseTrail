# Desktop releases

Use one GitHub Actions build and one local release record for Windows x64 and
Intel macOS. The local command signs both targets with the existing offline key
and promotes the same bytes through staging and production. Apple Silicon is
deferred. Server deployment is separate unless the desktop API contract changes.

## One-time setup

On the trusted signing/publishing computer, use the existing client development
environment. Install GitHub CLI and run `gh auth login` for repository/Actions
read access. SSH access to the artifact host is also required.

Copy `client/desktop-release-config.example.json` to ignored
`client/desktop-release-config.json`. Set the release storage directory, existing
encrypted signing-key path, and staging/production destinations. Keep the key
outside the checkout and artifact directories. No signing or server credentials
are installed in GitHub Actions. Native build tools are needed only on CI runners.

The workflow must be merged into the default branch before its **Run workflow**
button is available. Tags created before the build-only tooling, including the
accepted `client-v1.4.2`, use the adoption path below.

Changes to packaging tooling on development branches also trigger native build
validation. Those isolated checkouts use a temporary local tag and retain clearly
named `client-validation-*` artifacts. The release command rejects these runs;
they exercise the builders without creating or changing any release tag.

## Normal release

1. Commit the intended version and create/push its `client-vX.Y.Z` tag. In
   **Actions > Build desktop release > Run workflow**, enter that tag. Both native
   jobs must pass. Each runs the source suite, packages its installer, and checks
   frozen runtime, architecture, and offline behavior. Copy the successful run ID.
2. From `client/`, retrieve, verify and sign both installers with one command:

   ```bash
   uv run --no-env-file --no-sync python -m scripts.desktop_release prepare --run RUN_ID --tag client-vX.Y.Z
   ```

   The tag must also exist in the local checkout (`git fetch origin --tags` if
   needed). The command verifies the workflow/run, both immutable download hashes,
   source/tag/target identity, Python and build reports before asking once for the
   signing-key passphrase. It preserves builder metadata when signing on another
   OS. Output is `<releases_dir>/X.Y.Z/desktop-release.json` plus both signed targets.
3. Install those exact candidates in the test profiles. Check About, startup,
   offline restart, and functionality affected by the release. Use CI for the
   automated regression suite; do not repeat the full historical walkthrough for
   unrelated changes. Then promote with the commands below.

Installer bytes never change during signing or promotion. Failed/expired CI runs
must be rebuilt and accepted as new candidates; a previously prepared local
release does not depend on continued Actions artifact retention.

## Review and promote

```bash
uv run --no-env-file --no-sync python -m scripts.desktop_release publish X.Y.Z --environment staging
```

Without `--activate`, this verifies both saved targets and prints a concise
destination/installer summary without contacting the server. After native
acceptance, append `--activate`. One explicit confirmation covers the pair.
Uploads verify remote bytes before activating each channel and testing its public
download. Both targets must pass staging before production activation:

```bash
uv run --no-env-file --no-sync python -m scripts.desktop_release publish X.Y.Z --environment production --activate
```

The saved record tracks each target. A retry reconciles the server's active
pointer, verifies already uploaded files, and uploads only missing identical
files. It does not rebuild, re-sign, overwrite existing artifact bytes, or roll
back a newer sequence. Two channel switches are not atomic: a second-target
failure leaves the first target's recorded success intact. Inspect progress with:

```bash
uv run --no-env-file --no-sync python -m scripts.desktop_release status X.Y.Z
```

If a remote file differs, stop and investigate using the existing
[artifact rollback guide](artifact-rollback.md). Do not alter the record's hashes
or replace accepted files to force a retry through.

## Adopt the accepted 1.4.2 installers

The accepted native builds predate the CI workflow. Preserve them, including each
target's `client-manifest.json`, `client-manifest.sig`, installer, and original
`release-inventory.json`. Place each four-file set under its target directory
inside one local input root. The checked-in
[1.4.2 evidence](../client/releases/client-v1.4.2.json) contains the inventory
digests recorded during acceptance.

```bash
uv run --no-env-file --no-sync python -m scripts.desktop_release adopt --from-dir INPUT_ROOT --evidence releases/client-v1.4.2.json
```

This independently verifies both signatures, inventory anchors, installers and
tag identity, then copies the unchanged files into the normal release layout.
It does not request the signing key. The existing Windows/Intel owner walkthroughs
remain accepted; routine `status` and `publish` commands now apply to this pair.

The one-time [1.3-to-1.4 API/website transition](client-release-contract.md) passed
its staging deployment, rollback/redeployment, and public-route/browser checks;
see the [recorded evidence](engineering-acceptance.md#client-142-staging-transition-september-26-2026).
Production activation remains pending its approval and normal deployment gates.
Adoption itself does not deploy the API or bypass those gates.
