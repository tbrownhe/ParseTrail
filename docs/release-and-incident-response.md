# Release and incident response

This is the cross-component checklist. Detailed commands live in the
[desktop release guide](../client/README.md), [server deployment runbook](../deployment.md),
[artifact rollback guide](artifact-rollback.md), and
[PostgreSQL restore/upgrade runbook](postgresql-17-upgrade.md).

## Release checklist

1. **Classify the release.** Decide whether it changes desktop code, the plugin
   catalog, server images, database schema, or more than one boundary. A parser-only
   change should not force an installer or server-image rebuild.
2. **Review and test.** Start from a clean branch, run the component suites and
   disposable PostgreSQL 17 stack, review generated-client changes, and require
   green hosted CI. Real statements remain local fixtures and must not enter Git,
   CI artifacts, or test output.
3. **Prepare compatibility.** Bump the client version for installer changes and
   set each plugin's version/minimum-client requirement honestly. Release a client
   containing new public trust keys before using those keys to sign artifacts.
4. **Tag exactly.** Client release tags are `client-v<version>` at `HEAD`; plugin
   tags are operator-chosen immutable release identifiers. Do not move a published
   tag or reuse an installer version/release sequence.
5. **Build once.** Run the unified local release command. It synchronizes the
   locked Python, runs tests, builds, smoke-tests the frozen executable when
   applicable, signs the exact manifest with the offline key, independently
   verifies it, and records tool versions/checksums. Inspect the dry run before
   adding `--publish`.
6. **Publish atomically.** Upload immutable release files before changing
   `current-release.json`. Verify public manifest/signature bytes and range-download
   the selected artifact. The offline private key never goes to the server or CI.
7. **Deploy server images through the gate.** Use commit-tagged digest-pinned
   images, recent restore evidence, explicit Alembic migration, bounded health
   waits, public smoke tests, and a recorded rollback target. Do not use the
   automatic application rollback path for a destructive schema migration.
8. **Observe and record.** Confirm dashboard login/logout, plugin update, installer
   listing/download, statement-submission rejection/success boundaries, database
   health, and logs. Keep the signed inventory and deployment record.

Windows Authenticode and Apple Developer ID/notarization are not part of the
current release gate. ParseTrail's Ed25519 manifest proves application-release
integrity but does not remove operating-system publisher warnings.

## Incident response principles

- Put user-data protection ahead of uptime.
- Stop writes/publication before changing evidence.
- Preserve timestamps, immutable release records, relevant logs, database state,
  and hashes. Do not copy statement plaintext into tickets or chat.
- Work from known-clean administration and release machines.
- Treat a secret as compromised if its exposure cannot be ruled out.
- Record what was exposed, for what interval, and which users/artifacts are
  affected. Communicate facts and uncertainty separately.

## Initial triage

1. Record detection time, reporter, affected host/version, and observable symptoms.
2. Classify the likely boundary: local device, public account/API, contributed
   statement storage, deployment registry, or offline release key.
3. If active exploitation or unexplained writes are possible, enable maintenance
   or remove the affected service from public routing. Stop artifact pointer changes
   and statement intake as appropriate.
4. Snapshot or otherwise preserve relevant logs, release-state JSON, database
   metadata, container/image digests, and ciphertext inventory without decrypting
   statements.
5. Use the reconciliation and manifest-verification tools from a clean checkout to
   distinguish missing/orphan files, pointer changes, and signature/digest failure.

## Response by boundary

### Public server or backend secrets

- Assume PostgreSQL account data and plaintext operational metadata were visible.
- If the attacker could access both ciphertext and `MASTER_KEY`, assume contributed
  statement contents were recoverable. RSA private-key access also exposes incoming
  payload keys observed during compromise.
- Rotate `SECRET_KEY` to invalidate every JWT, PostgreSQL and SMTP credentials,
  infrastructure credentials, and other exposed secrets. Rotate the RSA submission
  generation only after preserving the old keyring needed for already stored/in-flight
  data. Master-key rotation requires a separately designed re-encryption/recovery
  procedure; do not simply replace it and strand ciphertext.
- Rebuild from reviewed source and known base images, restore into disposable
  targets first, then run migrations, reconciliation, and public smoke tests.
- Notify affected contributors with the known exposure window and metadata/content
  assessment. Do not claim ciphertext was safe if the live host held its key.

### Artifact host only

- Freeze `current-release.json` changes and copy the public release directories for
  evidence.
- Verify manifests/signatures with bundled public keys and compare immutable local
  release inventories. If signed bytes and artifact hashes remain valid, clients
  retain integrity even if availability/pointers were attacked.
- Restore a previously verified immutable release using the rollback guide. Never
  rebuild an old version to simulate rollback.

### Offline Ed25519 private key

- Stop all artifact publication and consider every still-trusted key compromised.
- Prepare a new offline key and a clean client trust-store release that removes the
  old public key. If the old key cannot safely authenticate that transition,
  distribute and verify the recovery installer through an independent trusted
  channel; a manifest signed only by the compromised key is not evidence.
- Publish new catalogs only after unaffected clients trust the replacement key.
  Document the last known-good signature/release sequence and notify users to avoid
  updates in the affected interval.

### Local user device

- Treat the SQLite database, archive, backups, logs, cached artifacts, and saved
  dashboard token as exposed to the device account's level of compromise.
- Revoke server sessions by changing the account password; clear the OS credential
  entry; preserve a copy only if needed for forensics; restore from a verified
  backup onto a clean, encrypted device.
- A server secret rotation is not required unless server credentials or maintainer
  keys were present on the device.

## Recovery and closure

Before restoring normal service, require clean health checks, schema revision,
signed artifact verification, statement file/row reconciliation, account/session
tests, and an actual restore test. Monitor authentication, upload, artifact, and
proxy logs for recurrence.

Close the incident with a short record of scope, root cause, timeline, rotations,
user communication, recovery evidence, and follow-up owners. Add a regression or
runbook guard for the failure mode. Security reports follow [SECURITY.md](../SECURITY.md).
