# ParseTrail development guide

This guide starts from a clean checkout. Windows x64 and Intel macOS (x86_64) are
the active desktop development platforms. The owner has an Intel Mac; native
Apple Silicon (arm64) work is deferred until test hardware is available and does
not block Windows/Intel releases. Linux source execution is useful for development,
but its packaging, desktop integration, and credential-store behavior are still
experimental.

## Engineering contracts

These constraints apply when changing any component:

- Decrypted contributed statements exist only in process memory, including in
  developer tools. Never write those bytes to temporary files, logs, reports, or
  the workstation. Ordinary user-selected local statements and managed archives
  have the separate storage policy in [Privacy and data flow](docs/privacy-and-data-flow.md).
- Authenticate downloaded executable artifacts with the offline signing trust
  store before activation. The public server and CI never receive the private
  signing key. Models are local-only; any future remote model channel needs a
  signed release contract first.
- A failed import must not move the only source and then roll back its database
  transaction. Preserve the [client import/recovery contract](client/README.md#imports-and-recovery).
- Automated tests must not discover or connect to production through the root
  `.env`. Backend teardown removes only records created by the test run; the
  isolation suite checks that a pre-existing sentinel survives. Client tests use
  a temporary profile and null keyring.
- Preserve exact money values and typed dates. Do not introduce binary floating
  point into financial storage or calculations; chart presentation is an explicit
  conversion boundary.
- Keep SQLAlchemy sessions and mutations in headless application services, with
  explicit transaction ownership. GUI adapters own prompts, progress, and external
  file/plot launching. Characterize existing behavior before moving boundaries.
- Breaking API, schema, plugin, and client changes are permitted. Provide a clear
  migration, restore path, or compatibility error instead of silently admitting
  incompatible data.

Existing financial fixtures referenced by the local `.env` are authorized for
confidential local testing. Read only the explicit fixture inputs needed for that
task; this authorization does not let automated suites load production database
settings. Use copied client databases for mutating acceptance, and commit only
synthetic fixtures or redacted evidence.

Use focused branches, commit and push reviewable chunks, and prepare candidate
artifacts/isolated profiles before requesting owner GUI or platform testing.
Keep [TODO](TODO.md) limited to unfinished work; move lasting behavior into the
component guides and dated verification into the
[engineering acceptance record](docs/engineering-acceptance.md) when a task closes.
Server P0 acceptance is complete. Client development should touch the server only
when it exposes an interface requirement; unrelated infrastructure stays separate.

## Prerequisites

- Git
- [uv](https://docs.astral.sh/uv/) 0.12.5 or newer
- Docker Desktop on Windows/macOS, or Docker Engine with Compose on Linux
- Node.js 22.22.0 and npm for dashboard work (`frontend/.nvmrc` records it)

Release-only tools are documented under [Native release prerequisites](#native-release-prerequisites).
They are not needed to run tests or the application from source.

Clone the repository and confirm that it starts clean:

```bash
git clone https://github.com/tbrownhe/ParseTrail.git
cd ParseTrail
git status --short
```

Do not put real statements, SQLite databases, credentials, signing keys, or
Playwright authentication state in the checkout.

## Desktop client

uv provisions the exact Python patch release and uses the cross-platform lock:

```bash
cd client
uv python install 3.13.15
uv sync --extra dev --frozen --python 3.13.15
uv run --frozen --python 3.13.15 pytest -q
uv run --frozen --python 3.13.15 python src/parsetrail/main.py
```

The default database is `~/Documents/ParseTrail/parsetrail.db`. Application
configuration, logs, downloaded plugins, and cached public keys use the platform
application-data directory. Long-lived API credentials use Windows Credential
Locker or macOS Keychain rather than `config.json`.

To test local parsers against a private fixture directory without importing:

```bash
cd ..
uv run --project client --frozen --python 3.13.15 python \
  devtools/local_statements/batch_plugin_tester.py /path/to/statements
```

See [the client guide](client/README.md) for architecture, parser tests, database
migrations, release signing, and packaging.

## Full local web stack

Copy `.env.example.local` to `.env` and replace every required placeholder.
At minimum, choose unique values for the three passwords/secrets and absolute
host paths for `CLIENTS_DIR`, `PLUGINS_DIR`, and `STATEMENTS_DIR`. Docker Desktop
must be allowed to share those paths.

Generate suitable random values with the standard library:

```bash
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run --project backend python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Use the first form for `SECRET_KEY` and passwords and the second for
`MASTER_KEY`. Leave `STATEMENTS_FILE_OWNER` and `STATEMENTS_FILE_GROUP` empty on
Windows/macOS; numeric Unix IDs are optional for a Linux bind mount.

The database and submission-key volumes are external by design. Create them once:

```bash
docker volume create parsetrail_app-db-data
docker volume create parsetrail_app-keys-data
```

The production Compose file expects the external `traefik-public` network even
when local overrides remove proxy labels:

```bash
docker network create traefik-public
```

Run Alembic explicitly, then start the stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm prestart bash scripts/migrate.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --wait
```

Local endpoints are:

- API: <http://localhost:8000> (`/docs` and `/redoc`)
- dashboard: <http://localhost:8080>
- public website: <http://localhost>
- Adminer: <http://localhost:8090>
- PostgreSQL: `127.0.0.1:5432`

The development override publishes ports but does not mount source or enable
reload. Rebuild after containerized code changes:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --wait
```

Useful lifecycle commands:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Do not add `-v` to the normal shutdown command: that option removes Compose-owned
volumes. The two application volumes above are external, but preserving data by
habit is safer.

## Fast edit loops

To run the dashboard with Vite while the API stack is running:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop frontend
cd frontend
npm ci
cp .env.example .env
npm run dev -- --host
```

`frontend/.env.example` points at `http://localhost:8000/api/v1`. Production and
container deployments instead generate a validated, no-cache
`runtime-config.js` when the container starts.

To run FastAPI directly, keep the local PostgreSQL container running and export
the same settings from the root `.env`, with `POSTGRES_SERVER=localhost`. Then:

```bash
cd backend
uv python install 3.13.15
uv sync --extra dev --frozen --python 3.13.15
uv run --frozen --python 3.13.15 python -m app.core.submission_keys provision
uv run --frozen --python 3.13.15 fastapi dev app/main.py
```

The key command uses `backend/keys` for a direct host run. Keep that directory
private and out of Git.

## Automated checks

### Backend

Backend tests refuse remote hosts and production-looking database names and do
not load the repository `.env`. From the repository root:

```bash
docker compose -p parsetrail-tests -f docker-compose.test.yml up -d --wait
cd backend
uv sync --extra dev --frozen --python 3.13.15
uv run --frozen --python 3.13.15 python app/tests_pre_start.py
uv run --frozen --python 3.13.15 python -m app.tests.migrate_test_db
uv run --frozen --python 3.13.15 pytest -q
cd ..
docker compose -p parsetrail-tests -f docker-compose.test.yml down -v
```

Static checks:

```bash
cd backend
uv run --frozen --python 3.13.15 ruff check app
uv run --frozen --python 3.13.15 ruff format --check app
uv run --frozen --python 3.13.15 mypy app
```

### Dashboard and website

```bash
cd frontend
npm ci
npm run lint
npm run test:website
npm run build
```

For browser tests, use the disposable PostgreSQL 17 integration stack, never a
developer or production database:

```bash
docker compose -f docker-compose.ci.yml up -d --build --wait
cd frontend
npx playwright install chromium
npx playwright test
cd ..
docker compose -f docker-compose.ci.yml down -v --remove-orphans
```

### Generated API client

After changing an API schema, run from the repository root:

```bash
./scripts/generate-client.sh
```

On Windows without a Bash shell, run `npm run generate-client` from `frontend`.
Commit the generated changes with the backend schema change; do not hand-edit
`frontend/src/client/generated`.

### Pre-commit

```bash
uvx pre-commit install
uvx pre-commit run --all-files
```

## Native release prerequisites

Normal feature work does not require these tools. Releases must start from the
tagged clean commit and use the commands in [client/README.md](client/README.md).

### Windows x64

- Install NSIS separately and ensure `makensis.exe` is on `PATH`.
- Do not set `MAKENSIS_PATH`; the build deliberately uses the standard tool
  discovery path.
- PowerShell 7 is recommended.

### Intel macOS

- The client lock includes Intel and arm64 dependency resolution, but this is
  not native application or installer acceptance. Develop and rehearse releases
  on the owner's Intel Mac. Apple Silicon builds, CI acceptance, and usability
  testing are deferred until suitable hardware is available.
- Install `create-dmg` and OpenSSL 3 with Homebrew. Intel dependency source builds
  may also require Rust and `pkg-config`:

```bash
brew install create-dmg openssl@3 pkg-config rust
export OPENSSL_DIR="$(brew --prefix openssl@3)"
```

The OpenSSL setting is a build input only; a released application must not require
Homebrew at runtime. The release preflight will be strengthened further under the
remaining reproducibility work in `TODO.md`.

## Private fixtures and server submissions

Private fixture directories may be supplied to the local tools, but their files
must remain outside Git. The server-submission devtool decrypts selected ciphertext
only in process memory. Its exact configuration and commands are in
[devtools/server_statements/README.md](devtools/server_statements/README.md).

See [Privacy and data flow](docs/privacy-and-data-flow.md) before handling real
financial documents, and [deployment.md](deployment.md) before changing a server.
