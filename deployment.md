# ParseTrail deployment

Docker Compose is the only supported server deployment path. The former Docker
Swarm scripts and template deployment workflows have been removed. Deployment
is manual on a trusted Linux host until the staging success/rollback/restore
rehearsals are complete; no GitHub runner receives production credentials,
release-signing keys, SSH access, or a production `.env`.

Traefik remains in the separate infrastructure repository. This repository owns
the database and the backend, dashboard, and website containers behind it.

The isolated LAN/VPN staging target is defined entirely by configuration and the
same Compose file. Its bootstrap, comparison arguments, desktop profile, and
acceptance sequence are in [docs/staging.md](docs/staging.md).

Production uses `docker-compose.yml` alone. Local ports and Adminer live in the
explicit `docker-compose.dev.yml`; the repository deliberately has no
auto-discovered `docker-compose.override.yml`.

## Release properties

- Backend, dashboard, and website images are built once on a clean checkout.
- The one `--env-file` selected for a Compose invocation is the runtime source;
  services do not silently load a second checkout-local dotenv file.
- Each build is tagged with the full Git commit, pushed, resolved to a registry
  digest, and recorded in a release descriptor. Production never rebuilds source.
- Base images and dependency installs are pinned. Production Compose accepts
  digest references supplied by the release tool.
- Alembic runs as a separate, logged phase. Normal `prestart` and service
  replacement never migrate the schema.
- A deploy must have a recent restore-drill evidence file and a recorded previous
  immutable release.
- Service health is bounded by a timeout. Public smoke failure automatically
  reactivates the previous image digests and smokes them again.
- Final JSON records under the release-state directory are append-only from the
  tool's perspective. The mutable `current-release.json` is only a pointer to the
  active rollback baseline.

The automated path permits only backward-compatible database migrations. A
contract/destructive migration needs a separate maintenance plan, a database
restore point, and an explicit data-reconciliation decision; do not feed one to
this automatic application-rollback path.

## Configuration

The production `.env` remains on the server with mode `600`. Existing application,
SMTP, PostgreSQL, bind-mount, and Traefik values remain required. Add:

```dotenv
DOCKER_IMAGE_BACKEND=ghcr.io/tbrownhe/parsetrail-backend
DOCKER_IMAGE_FRONTEND=ghcr.io/tbrownhe/parsetrail-frontend
DOCKER_IMAGE_WEBSITE=ghcr.io/tbrownhe/parsetrail-website
POSTGRES_IMAGE=postgres:17.11-bookworm@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0
POSTGRES_VOLUME_NAME=parsetrail_app-db-data-pg17
SUBMISSION_KEYS_VOLUME_NAME=parsetrail_app-keys-data
TRAEFIK_ALLOWED_IP_RANGES=0.0.0.0/0,::/0
```

Keep the PostgreSQL 12 image and volume values until the separate
[PostgreSQL 17 dump/restore runbook](docs/postgresql-17-upgrade.md) is complete.
Changing the image without changing to the restored volume is forbidden.
The submission-key volume is also explicit so a staging Compose project cannot
silently mount the production default. Production permits public application
traffic; staging sets only the actual LAN/VPN CIDRs.

Keep runtime records and credentials outside the `/srv/parsetrail` Git checkout.
Use three access-controlled locations under a dedicated production runtime root:

- `/srv/parsetrail-production/release-state` for preflight, migration, and final records;
- `/srv/parsetrail-production/release-input` for release and backup-evidence JSON;
- `/srv/parsetrail-production/secrets/smoke.json` for a dedicated active smoke account.

Copy [the smoke example](deployment/smoke-config.example.json), fill in the public
URLs and dedicated account, and set its mode to `600`. The credentials are used
in memory and are never written to release records.

If the deployment host cannot reach its own public address because the router does
not support NAT hairpinning, add `host_overrides` for the API, dashboard, and
website hostnames with the value `127.0.0.1`. The smoke runner preserves the URL
hostnames for TLS verification and HTTP routing while resolving their connections
to the local Traefik entrypoint. Do not replace the public URLs with loopback URLs,
disable certificate verification, or use this override as a substitute for a
separate off-host reachability check.

## 1. Build and publish away from production

The three server images live as public packages in GitHub Container Registry.
Public visibility lets both staging and production pull by digest without keeping
a registry credential on `silicide`. Publishing still requires authentication.

On the trusted local builder, create a classic GitHub personal access token with
only `write:packages`, keep it in the password manager, and pass it to Docker over
standard input. Do not put it in this repository, a dotenv file, shell history,
or the server:

```bash
docker login ghcr.io -u tbrownhe --password-stdin
```

Copy [the build environment example](deployment/build.env.example) outside the
checkout. It contains repository names, not production secrets.

From a clean commit, with registry authentication already configured:

```bash
python3 scripts/deployment/release.py build \
  --build-env /secure/parsetrail/build.env \
  --output /secure/parsetrail/releases/release.json \
  --push
```

The build refuses a dirty worktree. Without `--push`, it can write a
non-deployable local descriptor. `--dry-run` prints the commit-tagged build/push
plan and writes nothing. Transfer the pushed release descriptor to the server;
do not transfer source-built images by an unrecorded side channel.

The first command-line push creates private packages by default. In GitHub,
connect each package to `tbrownhe/ParseTrail`, retain repository permission
inheritance, and change all three package visibilities to **Public**. Confirm the
actual deployment contract from a host with no GHCR credentials:

```bash
docker pull ghcr.io/tbrownhe/parsetrail-backend@sha256:FULL_DIGEST
docker pull ghcr.io/tbrownhe/parsetrail-frontend@sha256:FULL_DIGEST
docker pull ghcr.io/tbrownhe/parsetrail-website@sha256:FULL_DIGEST
```

Use the digest references written into `release.json`; never transcribe a digest
from a tag by hand. A mutable commit tag is useful for discovery, but is not a
deployment identity.

## 2. Bootstrap the rollback baseline once

The gated workflow will not deploy until the currently running backend,
dashboard, and website are digest-pinned. For the first staging transition only:

1. Put the three digest references from a release descriptor into
   `BACKEND_IMAGE_REF`, `FRONTEND_IMAGE_REF`, and `WEBSITE_IMAGE_REF` in staging.
2. Pull them, run `backend/scripts/migrate.sh` explicitly through Compose, replace
   services with `--no-build --wait`, and run `public_smoke.py` manually.
3. Record that verified stack as the initial rollback baseline:

   ```bash
   python3 scripts/deployment/release.py adopt \
     --deploy-env /srv/parsetrail/.env \
     --state-dir /srv/parsetrail-production/release-state \
     --source-commit FULL_40_CHARACTER_COMMIT
   ```

Do not bootstrap production until this transition and an application rollback
have succeeded in staging. Every staging release command also supplies
`--production-env` and `--production-state-dir`; deploy/rollback additionally
supplies `--production-smoke-config`. The tool refuses shared storage, secrets,
targets, artifact inventories, or smoke credentials.

## 3. Record recent restore evidence

After restoring the database dump, encrypted statement/file backup, and
submission-key volume into disposable targets, record the three drill IDs:

```bash
python3 scripts/deployment/release.py backup-evidence \
  --database-dump /srv/backups/parsetrail/database.dump \
  --database-restore-id staging-db-restore-20260828 \
  --files-restore-id staging-files-restore-20260828 \
  --submission-keys-restore-id staging-keys-restore-20260828 \
  --output /srv/parsetrail-production/release-input/backup-evidence.json
```

The tool hashes the dump immediately. Preflight re-hashes it and rejects evidence
older than 48 hours by default. The restore IDs are operator attestations to real
completed drills, not substitutes for doing them.

## 4. Preflight

Check out the exact clean commit named in the release descriptor, then run:

```bash
python3 scripts/deployment/release.py preflight \
  --deploy-env /srv/parsetrail/.env \
  --state-dir /srv/parsetrail-production/release-state \
  --release /srv/parsetrail-production/release-input/release.json \
  --backup-evidence /srv/parsetrail-production/release-input/backup-evidence.json
```

Preflight validates the commit and all image digests, renders Compose, requires a
digest-pinned PostgreSQL image, pulls application images, re-hashes the database
backup, records the current Alembic revision and signed artifact inventories, and
captures the exact rollback target. It prints a deployment ID used below.

## 5. Migrate without replacing application services

Enter the maintenance window and run:

```bash
python3 scripts/deployment/release.py migrate DEPLOYMENT_ID \
  --deploy-env /srv/parsetrail/.env \
  --state-dir /srv/parsetrail-production/release-state
```

Migration output is streamed to the operator and saved under
`release-state/migration-logs`. Its SHA-256 and resulting Alembic revision are
added to the pending record. Failure stops here; application images are not
replaced.

## 6. Deploy, wait, smoke, and record

```bash
python3 scripts/deployment/release.py deploy DEPLOYMENT_ID \
  --deploy-env /srv/parsetrail/.env \
  --state-dir /srv/parsetrail-production/release-state \
  --smoke-config /srv/parsetrail-production/secrets/smoke.json \
  --timeout 180
```

The tool uses `docker compose up --no-build --wait` and then tests through the
public proxy:

- backend health, dashboard, and website;
- login with the dedicated smoke account;
- signed plugin manifest/signature plus a one-byte authenticated range download;
- client listing, signed manifest/signature, and a one-byte range download;
- authenticated statement submission with a deliberately invalid envelope,
  which must be rejected before any statement file is created.

On success, the final record contains timestamp, operator/host, Git commit,
schema revisions, exact image digests, signed artifact versions/hashes, backup
evidence, migration-log hash, smoke timings, and the exact rollback target.

If health or smoke fails, the previous image digests are automatically reactivated
and smoked. If that rollback also fails, the command exits with a critical error:
keep traffic in maintenance and use the recorded state rather than improvising.

## Explicit application rollback

To rehearse or intentionally reactivate the rollback target from a successful
deployment record:

```bash
python3 scripts/deployment/release.py rollback DEPLOYMENT_ID \
  --deploy-env /srv/parsetrail/.env \
  --state-dir /srv/parsetrail-production/release-state \
  --smoke-config /srv/parsetrail-production/secrets/smoke.json
```

This is an application-image rollback only. If the released migration was not
backward compatible or production accepted data that the old schema cannot
represent, keep maintenance enabled and restore/reconcile the database according
to the migration plan.

## CI boundary

Hosted CI only lints, tests, builds the dashboard, and starts a disposable smoke
stack. It has `contents: read` permission and no production or signing secrets.
Do not reintroduce automatic production deployment until the required successful
staging deployment, application rollback, and migration/restore rollback have all
been observed and recorded.
