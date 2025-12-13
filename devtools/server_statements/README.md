# Server-Hosted Statement Devtools

Dev-only UI for browsing encrypted statement uploads on the server, decrypting one with the master key, and handing the plaintext to the ParseTrail client’s `ParseTestDialog` so you can iterate on parsing plugins. Not for production builds or distribution.

## How it works
- Loads config from the repo-level `.env` (see required keys below).
- Optionally starts an SSH local-forward to the Postgres container (`ssh -L`) when `SSH_TUNNEL_ENABLE=true`.
- Queries `statement_uploads` and shows the latest rows in a filterable/sortable PyQt table.
- On “Decrypt & Parse”: fetches ciphertext via SSH from `REMOTE_STATEMENTS_DIR`, decrypts with AES-GCM using the stored `init_vector` and `auth_tag`, writes a temp file, rebuilds plugins, opens the client `ParseTestDialog`, then deletes the temp file on close.
- If `ENVIRONMENT=local`, the master key is pulled over SSH from the remote env file; otherwise it is read directly from `MASTER_KEY`.

## Prerequisites
- Python environment with the client installed (editable) or otherwise importable (`client/src` is added to `sys.path` automatically when run from repo root).
- Packages: PyQt5, SQLAlchemy, psycopg/psycopg2 (or psycopg3), cryptography, pydantic-settings, loguru.
- SSH access to the server that hosts encrypted statements and the Postgres container.
- Access to the master key (either locally via `MASTER_KEY` or remotely via SSH).

## Configuration (.env in repo root)
`settings.py` reads the top-level `.env` and will error if it is missing. Populate at least:

```
# environment
ENVIRONMENT=local              # local | production

# crypto
MASTER_KEY=base64_32_byte_key  # used when ENVIRONMENT != local

# database
POSTGRES_SERVER=...
POSTGRES_PORT=5432
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DB=...

# SSH / tunneling
SSH_TUNNEL_ENABLE=true         # start ssh -L to DB container
SSH_TUNNEL_LOCAL_PORT=55432
DB_CONTAINER_NAME=parsetrail-db-1
DB_CONTAINER_PORT=5432
REMOTE_HOST=...
REMOTE_USER=...
SSH_KEY_PATH=~/.ssh/id_rsa     # optional

# files / key fetch
REMOTE_STATEMENTS_DIR=/srv/parsetrail/resources/statements
REMOTE_ENV_PATH=/srv/parsetrail/.env   # where MASTER_KEY lives when ENVIRONMENT=local
```

## Running
From the repo root with your client dev environment active:

```bash
python devtools/server_statements/statement_tool.py
```

Workflow: refresh to load rows → filter/select a statement → “Decrypt & Parse”. The parser dialog will open with the temp copy; closing it deletes the file. Plugin code is recompiled on every parse to pick up local edits.

## Notes & safety
- Use the same virtual env that the `client` uses.
- Plaintext is written only to a temp file that is deleted after the dialog closes; still treat the machine as sensitive.
- `devtools/` should stay out of distributed builds/packages.
- If the client UI fails to open, confirm the client is installed/editable and plugins can build (see `client/README.md`).

## File map
- `statement_tool.py` — PyQt UI, table/filter, decrypt + handoff to client dialog.
- `settings.py` — Pydantic settings bound to the repo `.env`.
- `db.py` — SQLAlchemy engine + optional SSH tunnel helper.
- `orm.py` — `statement_uploads` model (includes IV/auth tag/metadata).
- `aes.py` — AES-GCM decrypt and metadata parsing.
- `ssh.py` — SSH helpers for master-key lookup and ciphertext fetch.
