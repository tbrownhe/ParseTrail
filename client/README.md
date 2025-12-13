# ParseTrail Client

The ParseTrail client is a standalone desktop application (Windows + macOS) that parses encrypted financial statements, manages a local SQLite database, and syncs with a FastAPI backend for plugin distribution, updates, and secure statement submission.

This README covers only the client application. Project-level architecture and backend details are documented in the root README.

## Requirements

The client uses a hybrid Conda + uv workflow for reproducible builds and fast dependency management:

## Requirements
* [conda](https://www.anaconda.com/docs/getting-started/miniconda/main) - environment + Python version management
* [uv](https://docs.astral.sh/uv/) - extremely fast package installer
* [NSIS](https://nsis.sourceforge.io/Main_Page) - Windows only: builds the setup .exe installer
* [create-dmg](https://github.com/create-dmg/create-dmg) - macOS only: builds the .dmg installer

Windows builds are done with NSIS; macOS builds produce a disk image containing a drag-and-drop .app bundle.

## Install Dependencies
### Windows
```powershell
cd client
conda env create -f dev_env_win64.yml
conda activate parsetrail-client
uv pip install -e "./[dev]"
```

### macOS
```bash
cd client
conda env create -f dev_env_macos.yml
conda activate parsetrail-client
uv pip install -e "./[dev]"
```

## Running the Client

To run the UI directly from source:

```bash
python src/parsetrail/main.py
```

This launches the PyQt-based GUI in development mode.

## Testing Plugins Locally

The client supports dynamically loaded parsing plugins.
You can exercise a plugin against local PDF/text statements:

```bash
python src/parsetrail/test_plugins_locally.py
```

This bypasses the GUI and is the fastest way to debug parsing logic.

## Build & Deploy Plugins

Plugins are compiled into encrypted `.pyc` bundles and pushed to the backend server, where client applications can securely download them. Note this will be done on the ParseTrail server whenever a PR is merged and is not necessary for plugin development by the community unless running a local backend for testing purposes.

### Before building:

1. Copy client `.env.example` → `.env`
2. Set `REMOTE_HOST`, `REMOTE_USER`, `REMOTE_CLIENT_DIR`, etc.
3. Ensure the backend container is running and accessible.

### Windows
```powershell
.\build_plugins.ps1
```

### macOS

Plugin deployment scripts are not implemented yet. Plugins can still be compiled locally via

```bash
python src/parsetrail/build_plugins.py
```

## Build & Deploy Client Installer

This produces a downloadable client installer and uploads it to the server. Note that the deployment phase will be handled by the ParseTrail server after PR merge.

### Before building:

- Ensure client .env is populated with deployment variables
- Bump the version number in [src/parsetrail/version.py](src/parsetrail/version.py)

### Windows

```powershell
.\build_client_win64.ps1
```

This assembles a frozen application via PyInstaller, then packages it into an NSIS installer.

### macOS
```bash
./build_client_macos.sh
```

This produces a .app bundle and a polished .dmg installer (with background, custom icon, and drag-and-drop target).
Code signing / notarization steps are included but disabled by default.

# Plugins & Plugin Manager

Plugins are intentionally decoupled from the client application:

- The client never imports plugins directly.

- Plugins are loaded at runtime via `importlib`.

- This allows new parsing modules to be deployed to users *without requiring a new client install*.

- Plugins do rely on imports from the client’s codebase; therefore their source directory lives inside `src/parsetrail/plugins` so IDEs can resolve references without errors.

## Why this structure?

- Plugins are distributed as signed .pyc files, not source code.

- Their directory does not have to follow standard Python package structure because importlib loads them from absolute paths.

- This pattern keeps the client lightweight while making plugin updates extremely flexible.
