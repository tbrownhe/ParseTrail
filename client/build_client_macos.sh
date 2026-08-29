#!/bin/bash
set -euo pipefail

error_exit() {
    echo "ERROR: $1" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || error_exit "Required command '$1' not found in PATH."
}

CLIENTS_DIR=""
SIGNING_KEY=""
PUBLISH=false
REMOTE_USER=""
REMOTE_HOST=""
REMOTE_CLIENTS_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clients-dir) CLIENTS_DIR="${2:-}"; shift 2 ;;
        --signing-key) SIGNING_KEY="${2:-}"; shift 2 ;;
        --publish) PUBLISH=true; shift ;;
        --remote-user) REMOTE_USER="${2:-}"; shift 2 ;;
        --remote-host) REMOTE_HOST="${2:-}"; shift 2 ;;
        --remote-clients-dir) REMOTE_CLIENTS_DIR="${2:-}"; shift 2 ;;
        *) error_exit "Unknown argument: $1" ;;
    esac
done

[[ -d "$CLIENTS_DIR" ]] || error_exit "clients directory does not exist: $CLIENTS_DIR"
[[ -f "$SIGNING_KEY" ]] || error_exit "signing key does not exist: $SIGNING_KEY"
if $PUBLISH; then
    [[ -n "$REMOTE_USER" && -n "$REMOTE_HOST" && -n "$REMOTE_CLIENTS_DIR" ]] \
        || error_exit "remote user, host, and clients directory are required with --publish"
fi

require_cmd create-dmg
require_cmd uv

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
CLIENTS_DIR="$(cd "$CLIENTS_DIR" && pwd)"
SIGNING_KEY="$(cd "$(dirname "$SIGNING_KEY")" && pwd)/$(basename "$SIGNING_KEY")"
PYTHON_VERSION_FILE="${SCRIPT_DIR}/.python-version"
[[ -f "$PYTHON_VERSION_FILE" ]] || error_exit "Missing Python version file: $PYTHON_VERSION_FILE"
PYTHON_VERSION=$(tr -d '[:space:]' < "$PYTHON_VERSION_FILE")
[[ -n "$PYTHON_VERSION" ]] || error_exit "Python version file is empty: $PYTHON_VERSION_FILE"

VERSION=$(sed -nE "s/^__version__[[:space:]]*=[[:space:]]*['\"]([^'\"]+)['\"]/\1/p" \
    src/parsetrail/version.py)
[[ -n "$VERSION" ]] || error_exit "Failed to determine client version"

APP_NAME="ParseTrail"
SRC_DIR="./src"
MODULE_PATH="./src/parsetrail/main.py"
BUILD_DIR="./build"
APP_PATH="${BUILD_DIR}/${APP_NAME}.app"
DIST_DIR="${CLIENTS_DIR}/macos"
DMG_PATH="${DIST_DIR}/parsetrail_${VERSION}_macos_setup.dmg"
[[ ! -e "$DMG_PATH" ]] \
    || error_exit "Versioned installer already exists: $DMG_PATH. Bump the client version first."

METADATA_DIR=$(mktemp -d -t parsetrail-release.XXXXXX)
BUILD_METADATA="${METADATA_DIR}/build-metadata.json"
cleanup() {
    rm -f -- "$BUILD_METADATA"
    rmdir -- "$METADATA_DIR" 2>/dev/null || true
}
trap cleanup EXIT

echo "Validating clean client-v${VERSION} release source..."
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.release_source client \
    --version "$VERSION" \
    --platform macos \
    --metadata-output "$BUILD_METADATA" \
    || error_exit "Release source validation failed."
SOURCE_COMMIT=$(uv run --frozen --python "$PYTHON_VERSION" python -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["source_commit"])' \
    "$BUILD_METADATA")
SOURCE_TAG="client-v${VERSION}"

echo "Synchronizing the locked client environment with Python $PYTHON_VERSION..."
uv sync --extra dev --frozen --python "$PYTHON_VERSION" \
    || error_exit "Failed to synchronize the locked client environment."
ACTUAL_PYTHON_VERSION=$(uv run --frozen --python "$PYTHON_VERSION" python -c \
    'import platform; print(platform.python_version())')
[[ "$ACTUAL_PYTHON_VERSION" == "$PYTHON_VERSION" ]] \
    || error_exit "Expected Python $PYTHON_VERSION but uv selected $ACTUAL_PYTHON_VERSION."

echo "Running client regression tests..."
uv run --extra dev --frozen --python "$PYTHON_VERSION" pytest -q \
    || error_exit "Client tests failed."
echo "Checking bundled plugin release trust keys..."
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.plugin_release check-trust-store \
    || error_exit "Plugin trust-store check failed."

echo "Building the executable with PyInstaller..."
uv run --frozen --python "$PYTHON_VERSION" pyinstaller \
    -n "$APP_NAME" \
    --clean \
    --noconfirm \
    --noconsole \
    --workpath "prebuild" \
    --distpath "$BUILD_DIR" \
    --paths "$SRC_DIR" \
    --hidden-import=openpyxl.cell._writer \
    --add-data "src/parsetrail/assets:parsetrail/assets" \
    --add-data "${BUILD_METADATA}:parsetrail" \
    --add-data "THIRD_PARTY_NOTICES.md:." \
    --add-data "licenses:licenses" \
    --add-data "migrations:migrations" \
    --add-data "alembic.ini:." \
    --add-data "assets:assets" \
    --icon "assets/parsetrail.icns" \
    "$MODULE_PATH" \
    || error_exit "Failed to build the executable."

echo "Smoke-testing the frozen executable..."
SMOKE_EXECUTABLE="${APP_PATH}/Contents/MacOS/${APP_NAME}"
[[ -x "$SMOKE_EXECUTABLE" ]] || error_exit "Frozen executable not found: $SMOKE_EXECUTABLE"
"$SMOKE_EXECUTABLE" --runtime-smoke-test || error_exit "Frozen runtime smoke test failed."

echo "Creating DMG installer..."
mkdir -p "$DIST_DIR"
create-dmg \
    --volname "${APP_NAME} ${VERSION} Installer" \
    --volicon "./assets/parsetrail.icns" \
    --background "./assets/dmg.png" \
    --window-pos 200 120 \
    --window-size 800 425 \
    --icon-size 128 \
    --icon "${APP_NAME}.app" 150 175 \
    --hide-extension "${APP_NAME}.app" \
    --app-drop-link 650 175 \
    "$DMG_PATH" \
    "$APP_PATH"

echo "Signing and independently verifying the macOS release..."
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.client_release sign \
    --private-key "$SIGNING_KEY" \
    --installer "$DMG_PATH" \
    --platform macos \
    --version "$VERSION" \
    || error_exit "Client release signing failed."
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.client_release verify \
    --release-dir "$DIST_DIR" \
    || error_exit "Client release verification failed."

echo "Recording checksums and release-tool versions..."
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.release_inventory \
    --release-dir "$DIST_DIR" \
    --source-commit "$SOURCE_COMMIT" \
    --source-tag "$SOURCE_TAG" \
    --kind client \
    --platform macos \
    --version "$VERSION" \
    --packager create-dmg \
    || error_exit "Release inventory generation failed."

if ! $PUBLISH; then
    echo "Signed macOS dry run completed; publication skipped."
    exit 0
fi

REMOTE_PLATFORM_DIR="${REMOTE_CLIENTS_DIR%/}/macos"
uv run --frozen --python "$PYTHON_VERSION" python -m scripts.immutable_publish \
    --release-dir "$DIST_DIR" \
    --manifest client-manifest.json \
    --signature client-manifest.sig \
    --inventory release-inventory.json \
    --remote "${REMOTE_USER}@${REMOTE_HOST}" \
    --remote-root "$REMOTE_PLATFORM_DIR" \
    || error_exit "Immutable macOS client publication failed."

echo "macOS release completed successfully."
