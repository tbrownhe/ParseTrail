# ParseTrail backend

The backend is a FastAPI/PostgreSQL service for public accounts, signed artifact
distribution, and encrypted statement contributions. It does not receive the
desktop SQLite database or ordinary statement imports.

Start with the repository [development guide](../development.md). Production and
staging operations use the guarded [deployment runbook](../deployment.md).

## Locked development environment

From `backend`:

```bash
uv python install 3.13.15
uv sync --extra dev --frozen --python 3.13.15
```

Use `uv run --frozen --python 3.13.15 ...` for backend commands. Activation is
optional; uv selects `backend/.venv` directly.

For a direct host run, configure the root `.env`, point PostgreSQL at a disposable
or local database, provision the submission keyring once, and start FastAPI:

```bash
uv run --frozen --python 3.13.15 python -m app.core.submission_keys provision
uv run --frozen --python 3.13.15 fastapi dev app/main.py
```

Container startup does not migrate the database implicitly. Run migrations as a
separate reviewed operation before starting an upgraded stack:

```bash
docker compose run --rm prestart bash scripts/migrate.sh
```

## Tests and static checks

Backend tests use the PostgreSQL 17 service in `docker-compose.test.yml`, ignore
the repository `.env`, and refuse remote hosts or production-looking database
names. From the repository root:

```bash
docker compose -p parsetrail-tests -f docker-compose.test.yml up -d --wait
cd backend
uv sync --extra dev --frozen --python 3.13.15
uv run --frozen --python 3.13.15 python app/tests_pre_start.py
uv run --frozen --python 3.13.15 python -m app.tests.migrate_test_db
uv run --frozen --python 3.13.15 pytest -q
uv run --frozen --python 3.13.15 ruff check app
uv run --frozen --python 3.13.15 ruff format --check app
uv run --frozen --python 3.13.15 mypy app
cd ..
docker compose -p parsetrail-tests -f docker-compose.test.yml down -v
```

## Alembic migrations

Alembic is the only schema-creation and schema-upgrade mechanism. Do not restore
`SQLModel.metadata.create_all`, delete migration history, stamp an unknown
database, or generate revisions against production.

After changing a model:

1. Start an isolated local PostgreSQL database at the current Alembic head.
2. Generate the candidate from `backend`:

   ```bash
   uv run --frozen --python 3.13.15 alembic revision --autogenerate -m "describe change"
   ```

3. Review every generated operation, constraints, indexes, data conversions, and
   downgrade behavior. Autogenerate is a draft, not a correctness proof.
4. Exercise upgrade on a copied populated database and test rollback or documented
   restore behavior.
5. Commit the revision with its model and tests.

Production migration is a separately logged phase in `deployment.md`. A newer
PostgreSQL server must never be pointed at the PostgreSQL 12 data directory; use
the [dump/restore runbook](../docs/postgresql-17-upgrade.md).

## Statement-submission keyring

The Compose `prestart` service is the single provisioning owner for the RSA
submission keyring. Importing the app never generates or rotates keys. Rotate
explicitly:

```bash
docker compose run --rm prestart python -m app.core.submission_keys rotate
docker compose run --rm prestart python -m app.core.submission_keys show-active
```

The active pointer changes atomically. Retained private generations allow workers
to decrypt uploads encrypted just before rotation. Do not delete generations
until clients have refreshed the public key and the in-flight/retry interval has
passed.

The contribution pipeline decrypts only in process memory and writes only new
AES-GCM ciphertext. This protects copied storage without its master key; it does
not protect against a live backend that can read ciphertext and keys. See
[Privacy and data flow](../docs/privacy-and-data-flow.md).

## Encrypted statement reconciliation

Compare registered rows with encrypted files without decrypting contents:

```bash
uv run --frozen --python 3.13.15 python scripts/reconcile_statements.py
```

The default is read-only and exits nonzero on drift. After reviewing that output,
encrypted orphans can be moved with both
`--quarantine-orphans /recovery/path` and `--apply`. Missing-file rows are only
reported and are never deleted automatically.

## Signed artifacts

The backend is an untrusted host for plugin and installer releases. It never has
the Ed25519 private signing key. Immutable releases contain exact signed manifest
bytes and artifacts; an atomic `current-release.json` selects the active release.
The client authenticates the signature, release sequence, compatibility, names,
sizes, and SHA-256 digest before activation.

Signing, verification, and release commands are in
[client/README.md](../client/README.md). Rollback is in
[docs/artifact-rollback.md](../docs/artifact-rollback.md).

## Browser authentication

The dashboard uses a host-only HttpOnly `SameSite=Strict` cookie. Production and
staging use the `__Host-` prefix and `Secure`; local HTTP uses an unprefixed
development cookie. Cookie-authenticated mutations and browser login/logout
require the exact `FRONTEND_HOST` origin. Desktop/API consumers retain bearer
tokens. See [web authentication](../docs/web-authentication.md).

## Email templates

Editable MJML is under `app/email-templates/src`; generated HTML is under
`app/email-templates/build`. Regenerate and review the HTML whenever an MJML
source changes, then test against a non-production SMTP target.
