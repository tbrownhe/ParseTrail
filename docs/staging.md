# Isolated staging

Staging is a configuration-only instance of the production application. It uses
the same `docker-compose.yml`, exact image digests, Alembic migrations, signed
artifact bytes, and smoke implementation. It has no staging-only backend code.

Its state is deliberately disposable and cannot address production-owned storage:

| Boundary | Production | Staging |
| --- | --- | --- |
| Compose project | `parsetrail` | `parsetrail-staging` |
| PostgreSQL volume | production PG volume | restored, uniquely named PG17 volume |
| submission keys | production external volume | new staging external volume |
| resources | `/srv/parsetrail/...` | `/srv/parsetrail-staging/...` |
| release records | `/srv/parsetrail/release-state` | `/srv/parsetrail-staging/release-state` |
| secrets/accounts | production credentials | staging-only app, DB, master, and smoke secrets |
| desktop | normal platform profile/keyring | `ParseTrail-Staging` profile/keyring |

The deployment tool reads the production environment only to compare protected
identifiers, paths, and values. It does not print their secret contents. Every
staging command fails if the production reference is omitted or reused.

## 1. Private names and trusted HTTPS

Use these names:

- `staging.parsetrail.com`
- `dashboard.staging.parsetrail.com`
- `api.staging.parsetrail.com`

They need valid DNS records so the existing Traefik HTTP-01 resolver can obtain
trusted certificates. On the owner's LAN, split DNS or hosts-file entries can
resolve them directly to `silicide`'s LAN address. A VPN DNS override can do the
same for remote testing.

The shared Compose definition attaches a target-specific IP allow-list middleware
to every HTTPS application router. Staging's `TRAEFIK_ALLOWED_IP_RANGES` must list
only the actual LAN/VPN ranges; public requests are denied even when public DNS or
a CDN can reach Traefik. Production explicitly allows public addresses. Confirm
the effective client address in Traefik before relying on this control, especially
when adding another proxy hop.

Do not start application traffic until all three names return the expected valid
certificate from an allowed client and return 403 from a non-allowed source.

## 2. Server state

Create an isolated root and external submission-key volume on `silicide`:

```bash
sudo install -d -m 700 -o tbrownhe -g tbrownhe /srv/parsetrail-staging
install -d -m 700 \
  /srv/parsetrail-staging/resources/clients \
  /srv/parsetrail-staging/resources/plugins \
  /srv/parsetrail-staging/resources/statements \
  /srv/parsetrail-staging/release-state \
  /srv/parsetrail-staging/release-input \
  /srv/parsetrail-staging/secrets
docker volume create parsetrail_app-keys-data-staging
```

Use the PostgreSQL 17 staging volume produced by the guarded dump/restore helper;
never reuse it for production. Copy `.env.example.staging` outside Git to
`/srv/parsetrail-staging/.env`, set mode 600, and replace every placeholder.
Use new random values for `SECRET_KEY`, `MASTER_KEY`, PostgreSQL/bootstrap
passwords, Swagger auth, and smoke credentials.

The production dump contains statement rows encrypted with the production master
key. Staging intentionally does not receive that key or the production ciphertext
and therefore must not expose those rows as retrievable submissions. After the
restore/count evidence is preserved and before staging application traffic, make
one explicit choice:

1. remove the copied `statement_uploads` rows from the staging database and begin
   with an empty staging contribution store (recommended for the current small
   installation); or
2. build a separately reviewed decrypt/re-encrypt migration.

Do not copy production ciphertext while using an unrelated staging master key and
leave the resulting broken rows in the UI. The live rehearsal pauses for owner
confirmation before applying option 1.

## 3. Signed artifacts and captured mail

The resource directories are distinct, but their public artifact bytes must match
production exactly. Copy the active `clients` and `plugins` trees into the empty
staging directories while preserving names and bytes. Preflight compares release
sequences, exact manifest/signature hashes, and artifact metadata and fails on any
difference.

Staging SMTP must point to a LAN-only capture service, not the production relay.
The deployment guard requires a non-empty, different `SMTP_HOST`. Confirm that the
capture inbox is empty and reachable, then use only staging test recipients. No
captured message should leave the LAN.

Copy `deployment/staging-smoke-config.example.json` outside Git, create a dedicated
active staging account, and set the file mode to 600. Keep the production smoke
file available as a read-only comparison; the staging username, password, and URLs
must all differ.

## 4. First immutable baseline and deployment

All staging invocations include the production comparison paths:

```bash
STAGING_ARGS=(
  --deploy-env /srv/parsetrail-staging/.env
  --production-env /srv/parsetrail/.env
  --state-dir /srv/parsetrail-staging/release-state
  --production-state-dir /srv/parsetrail/release-state
)
```

Shell variables are shown only to keep the examples readable. First bootstrap the
exact digest-pinned release and smoke it manually, then adopt it:

```bash
python3 scripts/deployment/release.py adopt \
  "${STAGING_ARGS[@]}" \
  --source-commit FULL_40_CHARACTER_COMMIT
```

For the next release, record staging restore evidence, then run the normal gate:

```bash
python3 scripts/deployment/release.py preflight \
  "${STAGING_ARGS[@]}" \
  --release /srv/parsetrail-staging/release-input/release.json \
  --backup-evidence /srv/parsetrail-staging/release-input/backup-evidence.json

python3 scripts/deployment/release.py migrate DEPLOYMENT_ID "${STAGING_ARGS[@]}"

python3 scripts/deployment/release.py deploy DEPLOYMENT_ID \
  "${STAGING_ARGS[@]}" \
  --smoke-config /srv/parsetrail-staging/secrets/smoke.json \
  --production-smoke-config /srv/parsetrail/secrets/smoke.json
```

The same release descriptor and image digests are later promoted to production;
do not rebuild them between targets.

## 5. Isolated desktop profile

The installed client selects staging before importing settings or keyring code.
Windows PowerShell:

```powershell
& 'C:\Program Files\ParseTrail\ParseTrail.exe' --staging https://api.staging.parsetrail.com/api/v1
```

macOS:

```bash
/Applications/ParseTrail.app/Contents/MacOS/ParseTrail \
  --staging https://api.staging.parsetrail.com/api/v1
```

The process uses `ParseTrail-Staging` application data and OS credential service.
Its SQLite database, managed imports, plugins, cached submission key, logs,
reports, downloads, configuration, and backups remain inside that profile. Path
validation rejects an attempt to select normal-profile data. The title and red
status marker remain visible for the life of the process.

Closing staging and launching normally returns to the production profile; no
machine-wide environment setting or config edit is made.

## 6. Statement-development target

Copy `devtools/server_statements/.env.example.staging` outside Git and run:

```powershell
uv run --project client --frozen --python 3.13.15 python devtools/server_statements/statement_tool.py --env-file C:\secure\parsetrail-staging-devtool.env
```

The red banner must say `STAGING` and identify `parsetrail-staging-db-1` before
decrypting or changing status. The tool fetches the staging master key and
ciphertext over SSH and retains the memory-only plaintext invariant.

## 7. Acceptance and rollback rehearsals

Using the isolated desktop and captured mailbox, verify account/login, plugin and
client download, a new statement submission, admin retrieval/decryption, email
verification/reset, and a complete staging backup/restore into a third disposable
target.

Then record:

1. one successful gated staging deployment;
2. one explicit application-image rollback with passing smoke checks; and
3. one failed/incompatible migration recovery using the verified database/file/key
   restore, not an automatic image rollback.

Only after those records exist may the PostgreSQL 17 production cutover and any
deployment runner be considered.
