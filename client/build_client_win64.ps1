$ErrorActionPreference = "Stop"

# --- Load project-level .env -------------------------------------------------
$projectRoot = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $projectRoot ".env"

if (-not (Test-Path $envFile)) {
    Write-Error "ERROR: .env file not found at $envFile"
    exit 1
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }

    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) {
        $key   = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key) {
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$condaEnv        = $env:CLIENT_CONDA_ENV
$distDir         = $env:CLIENTS_DIR
$remoteUser      = $env:REMOTE_USER
$remoteHost      = $env:REMOTE_HOST
$remoteDir       = $env:REMOTE_CLIENTS_DIR

if (-not $condaEnv -or -not $distDir -or -not $remoteUser -or -not $remoteHost -or -not $remoteDir) {
    Write-Error "One or more required environment variables are missing. Please check $envFile."
    exit 1
}

# --- Define dirs for build stages --------------------------------------------
$prebuildDir = Join-Path $PSScriptRoot "prebuild"
$buildDir    = Join-Path $PSScriptRoot "build"
$srcDir      = Join-Path $PSScriptRoot "src"
$clientDir   = Join-Path $distDir "win64"


# --- Activate the conda environment ------------------------------------------
try {
    Write-Host "Activating conda environment '$condaEnv'..."
    conda activate $condaEnv
} catch {
    Write-Error "ERROR: Failed to activate conda environment '$condaEnv'."
    exit 1
}

# --- Ensure NSIS is available in this conda env ------------------------------

$makensis = Join-Path $env:CONDA_PREFIX "NSIS\makensis.exe"
if (-not (Test-Path $makensis)) {
    Write-Error "makensis not found at $makensis (check NSIS install / conda env)"
    exit 1
}

$nsisScript = Join-Path $PSScriptRoot "scripts\win64_installer.nsi"
if (-not (Test-Path $nsisScript)) {
    Write-Error "NSIS Script not found at $nsisScript"
    exit 1
}

try {
    # --- Build the executable -------------------------------------------------
    Write-Host "Running PyInstaller..."

    pyinstaller `
        --clean `
        --noconfirm `
        --noconsole `
        -n "ParseTrail" `
        --workpath "$prebuildDir" `
        --distpath "$buildDir" `
        --paths $srcDir `
        --add-data "assets;assets" `
        --add-data "migrations;migrations" `
        --add-data "alembic.ini;." `
        --hidden-import="openpyxl.cell._writer" `
        --hidden-import="scipy._lib.array_api_compat.numpy.fft" `
        --hidden-import="scipy.special._special_ufuncs" `
        --splash "assets\splash.png" `
        --icon "assets\parsetrail_128px.ico" `
        (Join-Path $srcDir "parsetrail\main.py")

    # --- Create Install Package at dist\win64\parsetrail_version_win64_setup.exe
    Write-Host "Creating installer with NSIS..."

    $versionFile = Join-Path $srcDir "parsetrail\version.py"
    $versionLine = Get-Content $versionFile |
        Where-Object { $_ -match '^__version__\s*=\s*"(.*)"' } |
        Select-Object -First 1

    if (-not $versionLine -or -not $Matches[1]) {
        Write-Error "ERROR: Could not extract __version__ from $versionFile."
        throw
    }

    $version = $Matches[1]
    Write-Host "Found version: $version"

    # Package the installer using NSIS
    New-Item -ItemType Directory -Force -Path $distDir
    New-Item -ItemType Directory -Force -Path $clientDir
    & $makensis /V4 "-DVERSION=$version" "-DDIST=$distDir" $nsisScript

} catch {
    Write-Error "ERROR: Build or packaging failed. $($_.Exception.Message)"
    throw
}
finally {
    # --- Deactivate the conda environment ------------------------------------
    try {
        Write-Host "Deactivating conda environment..."
        conda deactivate
    } catch {
        # ignore
    }
}

# Prompt for deploy
$answer = Read-Host "Deploy client installer to server? (y/n)"

if ($answer -ne 'y' -and $answer -ne 'Y') {
    Write-Host "Aborted."
    exit 1
}

# Deploy client installers
try {
    Write-Host "Starting deployment..."

    if (-not (Test-Path $clientDir)) {
        Write-Warning "Local directory not found: $clientDir"
        exit 1
    }

    $remoteBase = $remoteDir.TrimEnd('/')

    Get-ChildItem -Path $clientDir -File | ForEach-Object {
        $localPath  = $_.FullName
        $fileName   = $_.Name
        $remotePath = "$remoteBase/$fileName"

        Write-Host "Syncing: $localPath -> $remotePath"
        $remoteSpec = "${remoteUser}@${remoteHost}:$remotePath"
        scp $localPath $remoteSpec
    }

    Write-Host "Deployment completed successfully."
} catch {
    Write-Error "ERROR: Deployment failed. $($_.Exception.Message)"
    throw
}

# --- Delete prebuild and build dirs ------------------------------------------
#Write-Host "Cleaning up build directories..."
#emove-Item -Recurse -Force $prebuildDir, $buildDir -ErrorAction SilentlyContinue

pause
exit 0
