#!/bin/bash
set -euo pipefail

error_exit() {
    echo "ERROR: $1" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || error_exit "Required command '$1' not found in PATH."
}

# ---------- Load project .env ----------
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  error_exit "Missing env file: $ENV_FILE"
fi

# Load environment variables from the project-level .env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Required vars
required_vars=("CLIENTS_DIR")
missing=()
for v in "${required_vars[@]}"; do
    if [[ -z "${!v:-}" ]]; then
        missing+=("$v")
    fi
done

if (( ${#missing[@]} > 0 )); then
    error_exit "Missing required environment variables: ${missing[*]}"
fi

echo "Environment loaded successfully."


# ---------- Initial setup ----------

# Navigate to the script directory
cd "$(dirname "$0")" || error_exit "Failed to navigate to script directory."

echo "Setting variables..."
APP_NAME="ParseTrail"
SRC_DIR="./src"
MODULE_PATH="./src/parsetrail/main.py"
BUILD_DIR="./build"
APP_PATH="${BUILD_DIR}/${APP_NAME}.app"
DIST_DIR="${CLIENTS_DIR}/macos"

# Extract version from version.py
VERSION=$(grep "^__version__" ./src/parsetrail/version.py | sed -E "s/__version__ = ['\"]([^'\"]+)['\"]/\1/") || true
if [[ -z "${VERSION:-}" ]]; then
    error_exit "Failed to determine version from src/parsetrail/version.py"
fi
DMG_PATH="${DIST_DIR}/parsetrail_${VERSION}_macos_setup.dmg"
[[ ! -e "$DMG_PATH" ]] \
    || error_exit "Versioned installer already exists: $DMG_PATH. Bump the client version before rebuilding."

# Ensure required commands exist
require_cmd create-dmg
require_cmd uv


# ---------- Python environment & build ----------

PYTHON_VERSION_FILE="${SCRIPT_DIR}/.python-version"
[[ -f "$PYTHON_VERSION_FILE" ]] || error_exit "Missing Python version file: $PYTHON_VERSION_FILE"
PYTHON_VERSION=$(tr -d '[:space:]' < "$PYTHON_VERSION_FILE")
[[ -n "$PYTHON_VERSION" ]] || error_exit "Python version file is empty: $PYTHON_VERSION_FILE"

echo "Synchronizing the locked client environment with Python $PYTHON_VERSION..."
uv sync --frozen --python "$PYTHON_VERSION" \
    || error_exit "Failed to synchronize the locked client environment."

ACTUAL_PYTHON_VERSION=$(uv run --frozen --python "$PYTHON_VERSION" python -c \
    'import platform; print(platform.python_version())') \
    || error_exit "Failed to determine the synchronized Python version."
[[ "$ACTUAL_PYTHON_VERSION" == "$PYTHON_VERSION" ]] \
    || error_exit "Expected Python $PYTHON_VERSION but uv selected $ACTUAL_PYTHON_VERSION."
echo "Release interpreter: Python $ACTUAL_PYTHON_VERSION"

echo "Checking bundled plugin release trust keys..."
uv run --frozen --python "$PYTHON_VERSION" python scripts/plugin_release.py check-trust-store \
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
"$SMOKE_EXECUTABLE" --runtime-smoke-test \
    || error_exit "Frozen runtime smoke test failed."
echo "Frozen runtime smoke test passed."

# ---------- DMG packaging ----------

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

# ---------- Code signing / notarization (TODO) ----------
# codesign --force --sign "Developer ID Application: Your Name (Team ID)" "$DMG_PATH"
# xcrun altool --notarize-app --primary-bundle-id "com.yourcompany.ParseTrail" --username "your-apple-id" --password "app-specific-password" --file "$DMG_PATH"
# xcrun altool --notarization-info <RequestUUID> --username "your-apple-id" --password "app-specific-password"
# xcrun stapler staple "$DMG_PATH"

# ---------- Application-level release signing ----------

[[ -n "${PLUGIN_SIGNING_KEY:-}" ]] \
    || error_exit "PLUGIN_SIGNING_KEY is required to sign the client installer."

echo "Signing the macOS client release..."
uv run --frozen --python "$PYTHON_VERSION" python scripts/client_release.py sign \
    --private-key "$PLUGIN_SIGNING_KEY" \
    --installer "$DMG_PATH" \
    --platform macos \
    --version "$VERSION" \
    || error_exit "Client release signing failed."

echo "Verifying the signed macOS client release..."
uv run --frozen --python "$PYTHON_VERSION" python scripts/client_release.py verify \
    --release-dir "$DIST_DIR" \
    || error_exit "Client release verification failed."

# ---------- Optional deploy ----------

read -r -p "Do you want to deploy the .dmg to server? (y/n): " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    deploy_vars=("REMOTE_USER" "REMOTE_HOST" "REMOTE_CLIENTS_DIR")
    for v in "${deploy_vars[@]}"; do
        [[ -n "${!v:-}" ]] || error_exit "$v is required for deployment."
    done
    REMOTE_BASE="${REMOTE_CLIENTS_DIR%/}"
    REMOTE_PLATFORM_DIR="${REMOTE_BASE}/macos"
    uv run --frozen --python "$PYTHON_VERSION" python scripts/immutable_publish.py \
        --release-dir "$DIST_DIR" \
        --manifest client-manifest.json \
        --signature client-manifest.sig \
        --remote "${REMOTE_USER}@${REMOTE_HOST}" \
        --remote-root "$REMOTE_PLATFORM_DIR" \
        || error_exit "Immutable macOS client publication failed."
else
    echo "Deployment cancelled."
fi

echo "Script execution completed successfully!"
