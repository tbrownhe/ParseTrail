# Server-hosted statement devtools

This development-only UI browses encrypted statement submissions, decrypts a
selected statement in memory, and passes its bytes directly to the ParseTrail
client's `ParseTestDialog`. It is not part of production client builds.

## How it works

- Selects configuration with an explicit `--env-file` for staging/production;
  local development may fall back to the repository `.env`.
- Optionally starts an SSH local forward to Postgres when
  `SSH_TUNNEL_ENABLE=true`.
- Queries `statement_uploads` and displays recent rows in a filterable table.
- For **Decrypt & Parse**, fetches encrypted bytes over SSH, decrypts them with
  AES-GCM, recompiles plugins, constructs `ParseInput(data=plaintext)`, and opens
  `ParseTestDialog`.
- The batch tester uses the same in-memory `ParseInput` path.
- When `SSH_TUNNEL_ENABLE=true`, database settings and the master key are read
  from `REMOTE_ENV_PATH` and ciphertext is read over SSH. Otherwise the explicit
  local PostgreSQL settings, `MASTER_KEY`, and `STATEMENTS_DIR` are used.

Neither parse path creates a plaintext statement file. The encrypted download and
the decrypted byte blob remain in process memory. Normal OS behavior such as swap,
hibernation, and crash dumps is outside that application-level guarantee.

## Prerequisites

- The client is installed editable or otherwise importable. Running from the
  repository root adds `client/src` to `sys.path` automatically.
- PySide6, SQLAlchemy, psycopg/psycopg2, cryptography, pydantic-settings, and loguru.
- SSH access to the host containing encrypted statements and Postgres.
- Access to the statement master key.

## Configuration

`settings.py` uses the top-level `.env` for local compatibility. Pass
`--env-file` for every staging or production operation; the tool selects it before
importing database or crypto settings and displays the environment, host/container,
database, and file path prominently. `PARSETRAIL_ENV_FILE` remains available for
automation, and an explicit empty value disables dotenv loading for import/test
isolation. Runtime operations reject incomplete configuration. Configure at least:

```dotenv
ENVIRONMENT=staging

PLUGINS_DIR=C:\path\to\parsetrail-resources\plugins

POSTGRES_SERVER=...
POSTGRES_PORT=5432
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DB=...

SSH_TUNNEL_ENABLE=true
SSH_TUNNEL_LOCAL_PORT=55432
DB_CONTAINER_NAME=parsetrail-db-1
DB_CONTAINER_PORT=5432
REMOTE_HOST=...
REMOTE_USER=...
SSH_KEY_PATH=~/.ssh/id_rsa

REMOTE_STATEMENTS_DIR=/srv/parsetrail/resources/statements
REMOTE_ENV_PATH=/srv/parsetrail/.env
```

## Running

From the repository root using the locked client environment:

```bash
uv run --project client --frozen --python 3.13.15 python devtools/server_statements/statement_tool.py --env-file C:\secure\parsetrail-staging-devtool.env
```

Refresh the table, filter or select a statement, and choose **Decrypt & Parse**.
Plugin code is recompiled for every parse so local edits are picked up.

For a headless regression pass over rows marked `plugin_status='ready'`:

```bash
uv run --project client --frozen --python 3.13.15 python devtools/server_statements/batch_plugin_tester.py --env-file C:\secure\parsetrail-staging-devtool.env
```

Use `--status pending` to diagnose submitted statements that do not yet have a
blessed parser baseline, or `--status all` for an explicitly requested complete
pass. These modes are read-only and do not change submission status.
Add `--diagnose-routing` to failures to log only the candidate plugin identifiers
remaining after the suffix, PDF metadata, header, and body stages. It never logs
the extracted statement text or PDF metadata values.

Warnings fail the headless run by default. After reviewing them, pass
`--accept-warnings` explicitly to bless warning-bearing results. Importing the
batch module or requesting `--help` does not open a database connection or import
Qt; the database and optional SSH tunnel are initialized only when a run starts.

## Safety notes

- Use the same virtual environment as the desktop client.
- Verify the red target banner before decrypting a row or changing its status.
- Do not add a temporary-file compatibility fallback. Parsers receive a filename,
  suffix, and byte blob through `ParseInput`.
- Avoid logging decrypted bytes, extracted text, keys, or unredacted parser output.
- Keep `devtools/` out of distributed builds and packages.

## File map

- `statement_tool.py` - Qt UI, decryption, and in-memory parser handoff.
- `batch_plugin_tester.py` - in-memory batch regression runner.
- `settings.py` - Pydantic settings loaded from the repository `.env`.
- `db.py` - SQLAlchemy engine and optional SSH tunnel.
- `orm.py` - `statement_uploads` model.
- `aes.py` - AES-GCM decryption and metadata parsing.
- `ssh.py` - SSH helpers for key lookup and ciphertext retrieval.
