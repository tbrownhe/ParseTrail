# Server-hosted statement devtools

This development-only UI browses encrypted statement submissions, decrypts a
selected statement in memory, and passes its bytes directly to the ParseTrail
client's `ParseTestDialog`. It is not part of production client builds.

## How it works

- Loads configuration from the repository-level `.env` (see below).
- Optionally starts an SSH local forward to Postgres when
  `SSH_TUNNEL_ENABLE=true`.
- Queries `statement_uploads` and displays recent rows in a filterable table.
- For **Decrypt & Parse**, fetches encrypted bytes over SSH, decrypts them with
  AES-GCM, recompiles plugins, constructs `ParseInput(data=plaintext)`, and opens
  `ParseTestDialog`.
- The batch tester uses the same in-memory `ParseInput` path.
- If `ENVIRONMENT=local`, the master key is read from the remote environment over
  SSH. Otherwise it is read from the local `MASTER_KEY` setting.

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

`settings.py` reads the top-level `.env` and reports an error if it is absent.
Configure at least:

```dotenv
ENVIRONMENT=local

MASTER_KEY=base64_32_byte_key
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

From the repository root with the client development environment active:

```bash
python devtools/server_statements/statement_tool.py
```

Refresh the table, filter or select a statement, and choose **Decrypt & Parse**.
Plugin code is recompiled for every parse so local edits are picked up.

For a headless regression pass over rows marked `plugin_status='ready'`:

```bash
python devtools/server_statements/batch_plugin_tester.py
```

Warnings fail the headless run by default. After reviewing them, pass
`--accept-warnings` explicitly to bless warning-bearing results. Importing the
batch module or requesting `--help` does not open a database connection or import
Qt; the database and optional SSH tunnel are initialized only when a run starts.

## Safety notes

- Use the same virtual environment as the desktop client.
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
