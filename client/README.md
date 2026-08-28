# ParseTrail Client

ParseTrail is a Windows and macOS desktop application that parses financial
statements, stores financial data in a local SQLite database, and talks to the
FastAPI backend for authenticated plugin distribution, application updates, and
optional encrypted statement submission.

## Requirements

uv provisions the exact Python patch release declared in `.python-version` and
installs the locked project environment. Platform installer creation uses one
native external tool.

- [uv](https://docs.astral.sh/uv/)
- [NSIS](https://nsis.sourceforge.io/Main_Page) for Windows installers
- [create-dmg](https://github.com/create-dmg/create-dmg) for macOS installers

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

## Signed plugin releases

Plugins are compiled into `.pyc` files and authenticated as one catalog. The
release manifest contains each plugin's safe filename, exact byte size, SHA-256
digest, Python bytecode identity, plugin version, and minimum client version.
The exact manifest bytes receive one detached Ed25519 signature.

The server stores immutable release directories, but it never receives the
private signing key and cannot create a release an installed client will trust.
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
runtime, and only then packages it with NSIS. `makensis.exe` may be on `PATH`, in
the standard NSIS installation directory. Versioned installer files are
immutable: the build stops if that version already exists, so bump
`src/parsetrail/version.py` first.

To deploy an already-built installer without rebuilding it:

```powershell
.\build_client_win64.ps1 -DeployOnly
```

macOS:

```bash
./build_client_macos.sh
```

This builds the `.app` and a drag-and-drop `.dmg`. Apple signing and notarization
are separate from ParseTrail's application-level artifact signatures and are
not yet enabled by default.

## Plugin architecture

Plugins remain decoupled from the client release so parsers can be updated
without shipping a new application:

- Source lives under `src/parsetrail/plugins` for development and IDE support.
- Release plugins are loaded at runtime with `importlib` only after
  authentication.
- Plugins may import stable interfaces from the client codebase.
- The signed manifest carries compatibility metadata, so a plugin never needs
  to execute merely to determine whether it can be loaded.
