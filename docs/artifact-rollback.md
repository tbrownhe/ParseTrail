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
   uv run --frozen python scripts/client_release.py verify --release-dir <client-release>
   uv run --frozen python scripts/plugin_release.py verify --plugin-dir <plugin-release>
   ```

4. Compare the inventory's source tag, commit, tool versions, sizes, and hashes
   with the release record. Stop if any evidence is missing or inconsistent.

## Client installer rollback

Client releases are independent under `data/clients/win64` and
`data/clients/macos`. For the affected platform, atomically replace its
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
