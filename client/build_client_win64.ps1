param(
    [Parameter(Mandatory = $true)]
    [string]$ClientsDir,
    [string]$SigningKey,
    [switch]$Publish,
    [string]$RemoteUser,
    [string]$RemoteHost,
    [string]$RemoteClientsDir,
    [switch]$DeployOnly
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ClientsDir -PathType Container)) {
    throw "ClientsDir does not exist or is not a directory: $ClientsDir"
}
$distDir = (Resolve-Path -LiteralPath $ClientsDir).Path
$privateKey = $SigningKey
$remoteDir = $RemoteClientsDir
if (-not $DeployOnly) {
    if (-not $privateKey -or -not (Test-Path -LiteralPath $privateKey -PathType Leaf)) {
        throw "SigningKey must name the encrypted release key for build/sign operations"
    }
    $privateKey = (Resolve-Path -LiteralPath $privateKey).Path
}
if ($DeployOnly) {
    $Publish = $true
}

# --- Define dirs for build stages --------------------------------------------
$prebuildDir = Join-Path $PSScriptRoot "prebuild"
$buildDir    = Join-Path $PSScriptRoot "build"
$srcDir      = Join-Path $PSScriptRoot "src"
$clientDir   = Join-Path $distDir "win64"
$pythonVersionFile = Join-Path $PSScriptRoot ".python-version"

if (-not (Test-Path -LiteralPath $pythonVersionFile)) {
    Write-Error "Python version file not found at $pythonVersionFile"
    exit 1
}

$pythonVersion = (Get-Content -LiteralPath $pythonVersionFile -Raw).Trim()
if (-not $pythonVersion) {
    Write-Error "Python version file is empty: $pythonVersionFile"
    exit 1
}

$versionFile = Join-Path $srcDir "parsetrail\version.py"
$versionContents = Get-Content -LiteralPath $versionFile -Raw
if ($versionContents -notmatch '(?m)^__version__\s*=\s*"([^"]+)"') {
    Write-Error "Could not extract __version__ from $versionFile"
    exit 1
}
$version = $Matches[1]
$buildMetadataPath = Join-Path ([System.IO.Path]::GetTempPath()) "parsetrail-build-$([guid]::NewGuid().ToString('N')).json"
$sourceJson = uv run --frozen --python $pythonVersion python -m scripts.release_source client `
    --version $version `
    --platform win64 `
    --metadata-output $buildMetadataPath
if ($LASTEXITCODE -ne 0) {
    throw "Release source validation failed with exit code $LASTEXITCODE"
}
$releaseSource = $sourceJson | ConvertFrom-Json
$installerPath = Join-Path $clientDir "parsetrail_${version}_win64_setup.exe"
$manifestPath = Join-Path $clientDir "client-manifest.json"
$signaturePath = Join-Path $clientDir "client-manifest.sig"
if ($DeployOnly -and -not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    Write-Error "Installer for client version $version was not found: $installerPath"
    exit 1
}
if (-not $DeployOnly -and (Test-Path -LiteralPath $installerPath)) {
    Write-Error "Versioned installer already exists: $installerPath. Bump the client version before rebuilding."
    exit 1
}


# --- Locate the external Windows installer compiler --------------------------
if (-not $DeployOnly) {
$makensisCommand = Get-Command "makensis.exe" -ErrorAction SilentlyContinue
$makensisCandidates = @(
    if ($makensisCommand) { $makensisCommand.Source }
    (Join-Path $env:ProgramFiles "NSIS\makensis.exe")
    (Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe")
) | Where-Object { $_ }
$makensis = $makensisCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $makensis) {
    Write-Error "makensis.exe was not found. Install NSIS and ensure it is on PATH or in its standard installation directory."
    exit 1
}
$makensis = (Resolve-Path -LiteralPath $makensis).Path

$nsisScript = Join-Path $PSScriptRoot "scripts\win64_installer.nsi"
if (-not (Test-Path $nsisScript)) {
    Write-Error "NSIS Script not found at $nsisScript"
    exit 1
}

try {
    Write-Host "Synchronizing the locked client environment with Python $pythonVersion..."
    uv sync --extra dev --frozen --python $pythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }

    $actualPythonVersion = uv run --frozen --python $pythonVersion python -c "import platform; print(platform.python_version())"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to determine the synchronized Python version (exit code $LASTEXITCODE)"
    }
    if ($actualPythonVersion.Trim() -ne $pythonVersion) {
        throw "Expected Python $pythonVersion but uv selected $($actualPythonVersion.Trim())"
    }
    Write-Host "Release interpreter: Python $actualPythonVersion"

    Write-Host "Running client regression tests..."
    uv run --extra dev --frozen --python $pythonVersion pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Client tests failed with exit code $LASTEXITCODE"
    }

    Write-Host "Checking bundled plugin release trust keys..."
    uv run --frozen --python $pythonVersion python -m scripts.plugin_release check-trust-store
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin trust-store check failed with exit code $LASTEXITCODE"
    }

    # --- Build the executable -------------------------------------------------
    Write-Host "Running PyInstaller..."

    uv run --frozen --python $pythonVersion pyinstaller `
        --clean `
        --noconfirm `
        --noconsole `
        -n "ParseTrail" `
        --workpath "$prebuildDir" `
        --distpath "$buildDir" `
        --paths $srcDir `
        --add-data "assets;assets" `
        --add-data "src\parsetrail\assets;parsetrail\assets" `
        --add-data "$buildMetadataPath;parsetrail" `
        --add-data "THIRD_PARTY_NOTICES.md;." `
        --add-data "licenses;licenses" `
        --add-data "migrations;migrations" `
        --add-data "alembic.ini;." `
        --hidden-import="openpyxl.cell._writer" `
        --hidden-import="scipy._lib.array_api_compat.numpy.fft" `
        --hidden-import="scipy.special._special_ufuncs" `
        --splash "assets\splash.png" `
        --icon "assets\parsetrail_128px.ico" `
        (Join-Path $srcDir "parsetrail\main.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    # Exercise PyInstaller's runtime hooks and extension-module loader before an
    # installer can be published. A bootstrap error in a windowed executable can
    # otherwise leave a modal error dialog open, so enforce a timeout as well.
    Write-Host "Smoke-testing the frozen executable..."
    $builtExecutable = Join-Path $buildDir "ParseTrail\ParseTrail.exe"
    if (-not (Test-Path -LiteralPath $builtExecutable)) {
        throw "Frozen executable not found at $builtExecutable"
    }

    $smokeProcess = Start-Process `
        -FilePath $builtExecutable `
        -ArgumentList "--runtime-smoke-test" `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden `
        -PassThru
    if (-not $smokeProcess.WaitForExit(30000)) {
        Stop-Process -Id $smokeProcess.Id -Force -ErrorAction SilentlyContinue
        throw "Frozen runtime smoke test timed out after 30 seconds"
    }
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Frozen runtime smoke test failed with exit code $($smokeProcess.ExitCode)"
    }
    Write-Host "Frozen runtime smoke test passed."

    # --- Create Install Package at dist\win64\parsetrail_version_win64_setup.exe
    Write-Host "Creating installer with NSIS..."

    Write-Host "Found version: $version"

    # Package the installer using NSIS
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    New-Item -ItemType Directory -Force -Path $clientDir | Out-Null
    & $makensis /V2 "-DVERSION=$version" "-DDIST=$distDir" $nsisScript
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS packaging failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        throw "NSIS did not create the expected installer: $installerPath"
    }

} catch {
    Remove-Item -LiteralPath $buildMetadataPath -Force -ErrorAction SilentlyContinue
    Write-Error "ERROR: Build or packaging failed. $($_.Exception.Message)"
    throw
}
}

Remove-Item -LiteralPath $buildMetadataPath -Force -ErrorAction SilentlyContinue

# Sign new installers offline; deployment-only mode must independently verify
# the existing release using only the bundled public trust store.
if ($DeployOnly) {
    Write-Host "Synchronizing the locked environment for release verification..."
    uv sync --frozen --python $pythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }
}

if (-not $DeployOnly) {
    Write-Host "Signing the Windows client release..."
    uv run --frozen --python $pythonVersion python -m scripts.client_release sign `
        --private-key $privateKey `
        --installer $installerPath `
        --platform win64 `
        --version $version
    if ($LASTEXITCODE -ne 0) {
        throw "Client release signing failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Verifying the signed Windows client release..."
uv run --frozen --python $pythonVersion python -m scripts.client_release verify `
    --release-dir $clientDir
if ($LASTEXITCODE -ne 0) {
    throw "Client release verification failed with exit code $LASTEXITCODE"
}

if (-not $DeployOnly) {
    Write-Host "Recording checksums and release-tool versions..."
    uv run --frozen --python $pythonVersion python -m scripts.release_inventory `
        --release-dir $clientDir `
        --source-commit $releaseSource.source_commit `
        --source-tag $releaseSource.source_tag `
        --kind client `
        --platform win64 `
        --version $version `
        --packager nsis
    if ($LASTEXITCODE -ne 0) {
        throw "Release inventory generation failed with exit code $LASTEXITCODE"
    }
}
$inventoryPath = Join-Path $clientDir "release-inventory.json"
if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
    throw "Release inventory was not found: $inventoryPath"
}
$inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
if ($inventory.source_commit -ne $releaseSource.source_commit -or $inventory.source_tag -ne $releaseSource.source_tag) {
    throw "Release inventory does not match the checked-out source"
}

# Publication requires the explicit -Publish switch. The unified release command
# obtains an additional typed confirmation before setting it.
if (-not $Publish) {
    Write-Host "Installer built successfully; deployment skipped."
    exit 0
}

# Deploy client installers
try {
    Write-Host "Starting deployment..."

    if (-not $remoteUser -or -not $remoteHost -or -not $remoteDir) {
        throw "REMOTE_USER, REMOTE_HOST, and REMOTE_CLIENTS_DIR are required for deployment"
    }

    if (-not (Test-Path $clientDir)) {
        Write-Warning "Local directory not found: $clientDir"
        exit 1
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $releaseSequence = [Int64]$manifest.release_sequence
    if ($releaseSequence -le 0) {
        throw "Signed client manifest has an invalid release sequence"
    }
    if ($manifest.artifacts.Count -ne 1 -or $manifest.artifacts[0].filename -ne (Split-Path $installerPath -Leaf)) {
        throw "Signed client manifest does not describe the expected Windows installer"
    }

    $remotePlatformDir = "$($remoteDir.TrimEnd('/'))/win64"
    uv run --frozen --python $pythonVersion python -m scripts.immutable_publish `
        --release-dir $clientDir `
        --manifest client-manifest.json `
        --signature client-manifest.sig `
        --inventory release-inventory.json `
        --remote "${RemoteUser}@${RemoteHost}" `
        --remote-root $remotePlatformDir
    if ($LASTEXITCODE -ne 0) {
        throw "Immutable Windows client publication failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Error "ERROR: Deployment failed. $($_.Exception.Message)"
    throw
}

exit 0
