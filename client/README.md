# ParseTrail Client

ParseTrail is a Windows and macOS desktop application that parses financial
statements, stores financial data in a local SQLite database, and talks to the
FastAPI backend for authenticated plugin distribution, application updates, and
optional encrypted statement submission.

## Requirements

uv provisions the exact Python patch release declared in `.python-version` and
installs the locked project environment. Platform installer creation uses one
native external tool.

- Python 3.13.15 (provisioned by uv; do not substitute another patch release)
- PySide6 Essentials 6.11.2 / Qt 6.11.2
- Windows 10 1809 or newer, or macOS 13 or newer
- [uv](https://docs.astral.sh/uv/)
- [NSIS](https://nsis.sourceforge.io/Main_Page) for Windows installers
- [create-dmg](https://github.com/create-dmg/create-dmg) for macOS installers

PySide6 replaced PyQt5 because ParseTrail is MIT-licensed while the freely
downloadable PyQt bindings are GPL-licensed. Desktop packages include the
PySide/Qt third-party notice and LGPLv3 text. Keep Qt libraries dynamically
replaceable when changing the packaging layout.

### Windows development environment

```powershell
cd client
uv sync --extra dev --frozen
```

### macOS development environment

```bash
cd client
uv sync --extra dev --frozen
```

## Run and test

Run the normal UI:

```bash
uv run --frozen python src/parsetrail/main.py
```

Run the automated suite:

```bash
uv run --frozen pytest
```

Exercise source plugins against local statement fixtures:

```bash
uv run --frozen python src/parsetrail/run_plugins_locally.py
```

The parser-development launcher explicitly enables unsigned local plugins and
logs that mode. The normal application has no unsigned mode.

## Local database and exact financial values

Client 1.3 stores monetary values as integer minor units with an explicit
currency code. Parser and application code use `Decimal`; conversion to float
occurs only at chart presentation boundaries. USD (two minor-unit digits) is the
only admitted currency today, so an unsupported currency fails explicitly
instead of being silently treated as dollars. Calendar-only statement and
transaction dates have no invented time zone. Generated import timestamps are
aware UTC values.

Transactions and statements have many-to-many membership. Overlapping CSV/XLSX
exports can therefore share one canonical transaction while both statements
retain their full row counts. Transaction identity uses a versioned,
length-framed SHA-256 fingerprint. New statement files use SHA-256 content
digests; migrated MD5 content digests remain only for duplicate-file
compatibility.

Database upgrades run against a same-directory shadow copy. ParseTrail validates
SQLite integrity, foreign keys, and the Alembic revision before atomically
replacing the original, and creates a collision-safe `.dbb` recovery copy first.
This precise-schema migration is intentionally not downgradable in place. To
recover, close ParseTrail, preserve the failed database for diagnosis, copy the
newest pre-migration `.dbb` beside it, and give the recovery copy the configured
`.db` filename.

Run a read-only, redacted preflight without printing account numbers,
descriptions, filenames, or balances:

```powershell
uv run --frozen python scripts/audit_client_database.py C:\path\to\client.db
```

## Offline startup and update checks

Parsing, categorization, clustering, and SQLite storage use bundled resources
and do not download package data. In particular, recurring-transaction
clustering uses ParseTrail's versioned English stop-word set instead of an NLTK
corpus.

By default, ParseTrail schedules a client/plugin update check three seconds
after the window is initialized. It never delays construction or first paint,
and a network failure does not prevent local use. Disable **Check for Client and
Plugin Updates After Startup** in Preferences for a completely network-silent
launch; manual update checks and optional statement submission remain available.

## Desktop login storage

ParseTrail stores its API access token in the operating system credential store:
Windows Credential Locker, macOS Keychain, or a supported Linux Secret Service or
KWallet backend. The token is never serialized into `config.json`. On a Linux
desktop without a secure keyring backend, the login remains in memory for the
current run and ParseTrail asks again after restart rather than falling back to a
plaintext or app-decryptable file.

Client 1.3 migrates an existing file-encrypted token once, rewrites the config
without it, and removes the obsolete `~/.parsetrail.key`. Clearing or invalidating
the login also deletes the OS credential.

## Signed plugin releases

Plugins are compiled into `.pyc` files and authenticated as one catalog. The
release manifest contains each plugin's safe filename, exact byte size, SHA-256
digest, Python bytecode identity, plugin version, and minimum client version.
The exact manifest bytes receive one detached Ed25519 signature.

The server stores immutable release directories, but it never receives the
private signing key and cannot create a plugin or installer release an installed
client will trust. The same offline Ed25519 release key currently signs both
artifact types; distributed clients contain only its public key.
Python bytecode is not encryption or obfuscation: signing detects unauthorized
changes but does not prevent decompilation.

### Provision the initial signing key

Choose a private-key location outside this repository and outside any
server-synchronized artifact directory. An encrypted removable drive is
recommended.

From `client/`, run:

```powershell
uv run --frozen python scripts/plugin_release.py generate-key `
    --private-key "X:\ParseTrail\plugin-signing-key.pem"
```

The command:

- prompts twice for a passphrase;
- writes an encrypted Ed25519 private key only to the explicit external path;
- adds only its public key to
  `src/parsetrail/assets/plugin-release-keys.json`; and
- refuses to put the private key anywhere inside the repository.

Back up the encrypted private key separately and commit the public trust-store
change. Never copy the private key to `parsetrail.com`, CI, this repository,
`parsetrail-resources`, or a client package. Do not store its passphrase in
`.env`, command arguments, or logs.

### Configure a local release builder

Copy `release-config.example.json` to the ignored
`release-config.json` and enter explicit local artifact directories, the
external signing-key path, and optional SSH deployment values. Build scripts do
not read the repository `.env`. The config contains no passphrase; signing
always prompts through the terminal.

Every release requires a clean worktree and an exact tag at `HEAD`. Client tags
are derived from `src/parsetrail/version.py`, for example:

```powershell
git tag client-v1.3.0
```

Plugin tags are explicit operator-chosen identifiers, such as
`plugins-2026.08.29.1`. Push a tag only after the dry run succeeds.

### Run a plugin release

From `client/`, the same command works on Windows and macOS:

```powershell
uv run --frozen python scripts/release.py `
    --config release-config.json plugins `
    --tag plugins-2026.08.29.1
```

The default is a dry run: it validates the clean tagged source, synchronizes the
locked Python patch release, runs all client tests, compiles the complete plugin
catalog, removes stale compiled output, prompts for the offline-key passphrase,
signs, independently verifies, and writes `release-inventory.json`. It does not
connect to or change the public server.

Add `--publish` only after inspecting the dry-run output. Publication requires a
second typed confirmation, uploads all files into a new immutable release
directory, compares their remote sizes and SHA-256 hashes, and atomically changes
`current-release.json` last. It then compares the public manifest and signature
with the local bytes and smokes the public listing or installer range endpoint.

For key rotation, first release a client that contains both old and new public
keys. Only start signing catalogs with the new key after that client is
available.

### Client trust behavior

The normal application:

- verifies the manifest signature before trusting catalog metadata;
- downloads every listed plugin into a staging release;
- enforces bounded reads, network timeouts, safe filenames, Python
  compatibility, exact sizes, and SHA-256 digests;
- changes the active release only after the complete catalog verifies;
- re-verifies every plugin before each startup and dynamic import; and
- rejects rollback, reused release sequence numbers, legacy unsigned plugins,
  partial downloads, and tampered local files.

Existing unsigned `.pyc` files are left in place but ignored. Cancellation or
any failed artifact preserves the previously verified release.

## Build and release the desktop installer

Before building, update `src/parsetrail/version.py`, commit it, and create the
matching `client-v<version>` tag. Both platform builders refuse a dirty tree,
missing/mismatched tag, reused versioned installer, or empty public-key trust
store. The source commit is embedded in the installed app and included with tool
versions and file checksums in `release-inventory.json`.

Windows:

```powershell
uv run --frozen python scripts/release.py `
    --config release-config.json client --platform win64
```

This synchronizes the locked environment using the exact Python patch release in
`.python-version`, builds the PyInstaller application, smoke-tests the frozen
runtime, packages it with NSIS, prompts for the offline release-key passphrase,
and independently verifies the signed installer manifest. Install NSIS normally;
`makensis.exe` may be on `PATH` or in its standard installation directory. No
`MAKENSIS_PATH` setting is used.

To publish, repeat the command with `--publish`. An interrupted upload cannot
replace the active release. If SSH drops during activation, the publisher reads
the authoritative pointer and distinguishes a completed activation from a failed
one. The same publisher is used for both installer platforms and plugins.

macOS:

```bash
uv run --frozen python scripts/release.py \
    --config release-config.json client --platform macos
```

This builds the `.app` and a drag-and-drop `.dmg`, signs its ParseTrail release
manifest with the same offline key, verifies it, and smoke-tests the actual
frozen executable. Run this gate on a real supported Mac. Apple signing and
notarization are separate from ParseTrail's application-level artifact signature
and are not yet enabled.

Client 1.3 understands the plugin manifest's signed source-commit field. Publish
the 1.3 client before the first plugin catalog generated by this release command;
older clients reject that catalog and retain their previously verified plugins.

See [artifact rollback](../docs/artifact-rollback.md) for restoring an earlier
immutable release without rebuilding or deleting release evidence.

## Plugin architecture

Plugins remain decoupled from the client release so parsers can be updated
without shipping a new application:

- Source lives under `src/parsetrail/plugins` for development and IDE support.
- Release plugins are loaded at runtime with `importlib` only after
  authentication.
- Plugins may import stable interfaces from the client codebase.
- The signed manifest carries compatibility metadata, so a plugin never needs
  to execute merely to determine whether it can be loaded.
- Parsing is headless: the core returns typed results, warnings, and redacted
  failures. GUI and batch adapters independently decide how to present or accept
  warnings.
- Routing walks suffix, optional PDF metadata, normalized page-header markers,
  and body-text expressions, then refuses zero or multiple matches.
