# Artifact rollback

Client installers and plugin catalogs are published into immutable numbered
directories. Never edit or delete a numbered release during rollback. Preserve
its manifest, detached signature, inventory, and artifacts for diagnosis.

API-image and PostgreSQL rollback are separate operations documented in
[`deployment.md`](../deployment.md).

## Before changing an active artifact

1. Record the active `current-release.json`, the intended target sequence, and
   the reason for rollback.
2. Confirm the target directory is beneath `releases/<sequence>/` and contains
   the files named by its manifest plus `release-inventory.json`.
3. Copy the target release to a trusted workstation and verify it with only the
   public key bundled in the corresponding source checkout:

   ```text
   uv run --no-env-file --frozen python -m scripts.client_release verify --release-dir <client-release>
   uv run --no-env-file --frozen python -m scripts.plugin_release verify --plugin-dir <plugin-release>
   ```

4. Compare the inventory's source tag, commit, tool versions, sizes, and hashes
   with the release record. Stop if any evidence is missing or inconsistent.

## Client installer rollback

Client 1.4 releases are independent under `data/clients/windows-x86_64` and
`data/clients/macos-x86_64`. Verify the version-2 manifest's explicit platform and
`architecture` against that channel and the inventory before selecting it. For
the affected target, atomically replace its
`current-release.json` with a pointer containing exactly:

```json
{"release_sequence": <KNOWN_GOOD_SEQUENCE>, "schema_version": 1}
```

Write and verify a temporary file in the same directory, then rename it over the
pointer so readers can never observe a partial document. Do not copy files into
the old release or reuse its sequence. Run the public manifest, signature,
installer range-download, listing, and website smoke checks from the production
deployment runbook. Restore the prior pointer if any check fails.

This changes the installer offered to new downloads. It does not and should not
silently downgrade an already installed desktop application.

Legacy 1.3 artifacts remain unchanged in `data/clients/win64` and
`data/clients/macos`. They cannot be placed behind a version-2 channel pointer or
verified by the new version-2-only client tooling. Use the matching old tagged
source/public trust store to verify them. Restoring service for old clients
requires the previous API/website version and the preserved legacy pointers;
changing only a new channel's pointer cannot restore the legacy update contract.
See the [coordinated transition](client-release-contract.md) before any rollback
across that boundary.

## Plugin rollback

Installed clients reject decreasing or reused plugin release sequences. Merely
pointing the server at an older sequence protects clients that have not installed
the bad catalog, but clients that already installed it retain their authenticated
local copy.

The durable rollback is therefore a roll-forward release of known-good plugin
source:

1. Temporarily point the server to the last known-good immutable sequence if
   immediate containment is needed.
2. Check out the known-good plugin tag and verify its commit and prior inventory.
3. Run the normal plugin dry run from that clean tagged checkout. It recompiles
   with the pinned interpreter and signs a new manifest whose sequence is greater
   than the faulty release.
4. Inspect the diff and inventory, publish with explicit approval, and run the
   plugin manifest, signature, authenticated range-download, and client-sync
   smoke checks.

Do not copy an old manifest to a new sequence or edit signed JSON. Either action
invalidates the signature and, if sequence reuse is attempted, correctly trips
the client's rollback protection.

## Local classification-model rollback

ParseTrail has no public model-download or model-release endpoint. Classification
models are local user artifacts selected by `model_path`; the former server route
is deliberately disabled. Roll back by closing ParseTrail, preserving the failed
model for diagnosis, restoring a known-good local backup into the configured
models directory, and selecting that exact file in local settings. If a future
public model channel is introduced, it must use the same signed immutable-release
and higher-sequence roll-forward policy as plugins before deployment is enabled.
