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
required_vars=("CLIENT_CONDA_ENV" "CLIENTS_DIR" "REMOTE_USER" "REMOTE_HOST" "REMOTE_CLIENTS_DIR")
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

# Ensure required commands exist
require_cmd conda
require_cmd create-dmg
require_cmd rsync


# ---------- Conda env & build ----------

CONDA_ENV="${CLIENT_CONDA_ENV}"
echo "Activating conda environment: $CONDA_ENV"
CONDA_BASE=$(conda info --base 2>/dev/null) || error_exit "Unable to determine conda base path."
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV" || error_exit "Failed to activate conda environment '$CONDA_ENV'."

echo "Building the executable with PyInstaller..."
pyinstaller \
    -n "$APP_NAME" \
    --clean \
    --noconfirm \
    --noconsole \
    --workpath "prebuild" \
    --distpath "$BUILD_DIR" \
    --paths "$SRC_DIR" \
    --hidden-import=openpyxl.cell._writer \
    --add-data "migrations:migrations" \
    --add-data "alembic.ini:." \
    --add-data "assets:assets" \
    --icon "assets/parsetrail.icns" \
    "$MODULE_PATH" \
    || error_exit "Failed to build the executable."

echo "Deactivating conda environment..."
conda deactivate || error_exit "Failed to deactivate conda environment."

# ---------- DMG packaging ----------

echo "Creating DMG installer..."
mkdir -p "$DIST_DIR"
rm -f "$DMG_PATH"

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

# ---------- Optional deploy ----------

read -r -p "Do you want to deploy the .dmg to server? (y/n): " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    echo "Deploying macOS client installer..."
    rsync -avz --progress "$DMG_PATH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_CLIENTS_DIR/"
    echo "Sync complete!"
else
    echo "Deployment cancelled."
fi

echo "Script execution completed successfully!"
