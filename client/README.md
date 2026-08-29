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

Set these non-secret paths and deployment values in the repository `.env`:

```dotenv
PLUGIN_SIGNING_KEY=X:\ParseTrail\plugin-signing-key.pem
PLUGINS_DIR=C:\path\to\parsetrail-resources\plugins
REMOTE_HOST=example
REMOTE_USER=example
REMOTE_PLUGINS_DIR=/path/to/data/plugins
```

### Build, sign, verify, and deploy on Windows

```powershell
.\build_plugins.ps1
```

The script runs the client tests, compiles every source plugin, removes stale
compiled output, prompts for the private-key passphrase, signs and independently
verifies the complete catalog, and asks before deployment. It uploads the
immutable release first and atomically changes `current-release.json` last.

### Compile and sign on macOS

The automated deployment wrapper is currently Windows-only. Compilation,
signing, and verification are platform-independent:

```bash
uv run --frozen python src/parsetrail/build_plugins.py
uv run --frozen python scripts/plugin_release.py sign \
    --private-key /Volumes/ParseTrail/plugin-signing-key.pem \
    --plugin-dir /path/to/plugins
uv run --frozen python scripts/plugin_release.py verify \
    --plugin-dir /path/to/plugins
```

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

## Build the desktop installer

Before building, update `src/parsetrail/version.py`. Both build scripts refuse to
package a client while the plugin public-key trust store is empty.

Windows:

```powershell
.\build_client_win64.ps1
```

This synchronizes the locked environment using the exact Python patch release in
`.python-version`, builds the PyInstaller application, smoke-tests the frozen
runtime, packages it with NSIS, prompts for the offline release-key passphrase,
and independently verifies the signed installer manifest. `makensis.exe` may be
on `PATH` or in the standard NSIS installation directory. Versioned installer
files are immutable: the build stops if that version already exists, so bump
`src/parsetrail/version.py` first.

If packaging succeeded but signing was interrupted, resume without rebuilding:

```powershell
.\build_client_win64.ps1 -SignOnly
```

To deploy an already-built installer without rebuilding it:

```powershell
.\build_client_win64.ps1 -DeployOnly
```

`-DeployOnly` does not access the private key. It re-verifies the local manifest
and installer using only the bundled public key, uploads all three files to a
new `win64/releases/<sequence>/` directory, independently compares remote sizes
and SHA-256 hashes, and atomically changes `win64/current-release.json` last. It
refuses to reuse a release sequence, and an interrupted upload cannot replace
the previously active release. If SSH drops during the atomic move, the publisher
reads the authoritative pointer and distinguishes a completed activation from a
failed one. The same tested publisher is used for Windows/macOS installers and
the plugin catalog. Deploy the backend manifest routes before the first installer
that uses this layout.

Python bytecode changed with the 3.13 client baseline. Publish client 1.2.2 (or
newer) before publishing plugins compiled with Python 3.13. Older clients reject
the incompatible catalog and retain their previously verified plugin release.

macOS:

```bash
./build_client_macos.sh
```

This builds the `.app` and a drag-and-drop `.dmg`, signs its ParseTrail release
manifest with the same offline key, verifies it, and uses the same immutable
upload/atomic-pointer protocol. Apple signing and notarization are separate from
ParseTrail's application-level artifact signature and are not yet enabled.

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
