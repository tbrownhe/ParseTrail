# PostgreSQL 12 to 17 upgrade

ParseTrail uses a logical `pg_dump`/`pg_restore` migration into a new Docker
volume. Never change the database image to PostgreSQL 17 while it still mounts
the PostgreSQL 12 data directory.

The migration helper deliberately does not stop application traffic or activate
the new database. It creates a restricted backup outside the repository,
restores it into a new volume, verifies every public table row count, and leaves
the original container and volume untouched.

The helper mounts the target volume root directly at PostgreSQL's configured
`PGDATA` directory (`/var/lib/postgresql/data/pgdata`). This must remain identical
to the database-volume target in `docker-compose.yml`; otherwise a verified
restore can be accidentally hidden one directory below the runtime mount.

## Prerequisites

- Record the current database container and volume names with `docker inspect`.
- Confirm the encrypted statement directory and the submission-key volume have
  separate current backups. They are not stored in PostgreSQL.
- Choose an absolute, access-controlled backup directory outside the checkout.
- Choose a new volume name, such as `parsetrail_app-db-data-pg17`. The helper
  refuses to reuse an existing target volume.
- Pull or pin an approved PostgreSQL 17 image before the maintenance window.

The custom-format dump contains account and operational data. Keep it encrypted
at rest with the rest of the server backup set, and do not copy it into Git.

## Rehearsal or migration

1. Stop every service that can write to PostgreSQL. Leave the PostgreSQL 12
   container running. Confirm that login, registration, downloads, and statement
   submission are unavailable during this window.
2. Run the helper from the repository root on the Docker host:

   ```bash
   POSTGRES_SOURCE_CONTAINER=parsetrail-db-1 \
   POSTGRES_TARGET_VOLUME=parsetrail_app-db-data-pg17 \
   POSTGRES_BACKUP_DIR=/srv/backups/parsetrail/postgres-upgrade \
   POSTGRES_WRITES_STOPPED=YES \
   bash scripts/postgres/upgrade-12-to-17.sh
   ```

   Set `POSTGRES_TARGET_IMAGE` to an approved immutable PostgreSQL 17 image
   reference when one is available. The helper aborts if another database
   session remains connected, if the source is not major version 12, or if the
   target volume already exists.
3. Preserve the `.dump`, `.sha256`, both `.counts.tsv` files, and generated
   `.cutover.env` file together. Validate the checksum from separate backup
   storage.

## Staging verification

Set the two generated cutover values together in a staging deployment:

```dotenv
POSTGRES_IMAGE=postgres:17.11-bookworm@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0
POSTGRES_VOLUME_NAME=parsetrail_app-db-data-pg17
```

Start the database first, run `backend/scripts/migrate.sh` explicitly through the
one-shot Compose service, then run the normal `prestart` service. Migration must
reach Alembic head and prestart must complete key/initial-data validation before
backend workers start. A staging restore must then run the one-time identity and
submission sanitizer documented in [staging.md](staging.md); row-count parity is
evidence that the restore succeeded, not permission to expose copied production
password hashes. Verify:

- expected row counts and the Alembic head;
- account registration, email verification, login, and password reset;
- plugin catalog and client download;
- statement submission, encrypted-file registration, and admin retrieval;
- backup and restore into another disposable PostgreSQL 17 volume.

Do not reuse the production target volume for a staging rehearsal. Use a unique
volume and delete it only after the rehearsal is accepted.
The full isolated target and its production-comparison guards are documented in
[staging.md](staging.md), including the guarded whole-boundary restore-drill tool.

## Production cutover and rollback

1. Take a fresh migration backup during a writer-free maintenance window.
2. Stop the PostgreSQL 12 container. Do not remove it or its volume.
3. Apply both `POSTGRES_IMAGE` and `POSTGRES_VOLUME_NAME` from the verified
   cutover file, start PostgreSQL 17, run `prestart` once, and then start the
   backend.
4. Run the public health and login/submission smoke checks before restoring
   normal traffic.

If verification fails before PostgreSQL 17 accepts production writes, stop the
new stack, restore both environment values to their PostgreSQL 12 defaults, and
restart the untouched old container. If PostgreSQL 17 has accepted writes, do
not blindly switch back: that would discard new data. Enter maintenance, take a
new logical dump, and make an explicit data-reconciliation plan.

Retain the PostgreSQL 12 volume and the pre-cutover dump until at least one full
backup cycle and restore drill have succeeded on PostgreSQL 17.

## Production acceptance record

The production cutover completed on 2026-08-31 using pinned PostgreSQL 17.11 and
volume `parsetrail_app-db-data-pg17`. The writer-free custom dump was restored and
every public-table count matched before activation. The resource archive restored
78 files with an identical cryptographic inventory, and the independent
`parsetrail_app-keys-data-restore-drill-20260831T0652Z` volume matched all five
submission-key files.

Deployment `20260831T065535Z-fedd236fb82a` migrated Alembic from
`39e1c1c2a803` to `3b7a1f4c2d91`, passed all seven authenticated public checks,
and wrote its append-only record under the production release-state directory.
An independent repeat smoke and off-host API/dashboard/website checks also passed.
The only post-restore row-count changes were two client-download and two
plugin-download audit rows produced by those two smoke runs. The original
`parsetrail_app-db-data` PostgreSQL 12 volume and restricted evidence under
`/srv/backups/parsetrail/production-cutover/20260831T0652Z` remain retained until
the hardened encrypted-backup job completes a PostgreSQL 17 full-boundary restore
drill.
