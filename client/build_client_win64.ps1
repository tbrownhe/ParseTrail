param(
    [switch]$DeployOnly,
    [switch]$SignOnly
)

$ErrorActionPreference = "Stop"

if ($DeployOnly -and $SignOnly) {
    throw "DeployOnly and SignOnly cannot be used together"
}
$skipBuild = $DeployOnly -or $SignOnly

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

$distDir         = $env:CLIENTS_DIR
$remoteUser      = $env:REMOTE_USER
$remoteHost      = $env:REMOTE_HOST
$remoteDir       = $env:REMOTE_CLIENTS_DIR
$privateKey      = $env:PLUGIN_SIGNING_KEY

if (-not $distDir) {
    Write-Error "CLIENTS_DIR is missing. Please check $envFile."
    exit 1
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
$installerPath = Join-Path $clientDir "parsetrail_${version}_win64_setup.exe"
$manifestPath = Join-Path $clientDir "client-manifest.json"
$signaturePath = Join-Path $clientDir "client-manifest.sig"
if ($skipBuild -and -not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    Write-Error "Installer for client version $version was not found: $installerPath"
    exit 1
}
if (-not $skipBuild -and (Test-Path -LiteralPath $installerPath)) {
    Write-Error "Versioned installer already exists: $installerPath. Bump the client version before rebuilding."
    exit 1
}


# --- Locate the external Windows installer compiler --------------------------
if (-not $skipBuild) {
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
    uv sync --frozen --python $pythonVersion
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

    Write-Host "Checking bundled plugin release trust keys..."
    uv run --frozen --python $pythonVersion python scripts/plugin_release.py check-trust-store
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
    Write-Error "ERROR: Build or packaging failed. $($_.Exception.Message)"
    throw
}
}

# Sign new installers offline; deployment-only mode must independently verify
# the existing release using only the bundled public trust store.
if ($skipBuild) {
    Write-Host "Synchronizing the locked environment for release verification..."
    uv sync --frozen --python $pythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }
}

if (-not $DeployOnly) {
    if (-not $privateKey) {
        throw "PLUGIN_SIGNING_KEY is required to sign the client installer"
    }
    Write-Host "Signing the Windows client release..."
    uv run --frozen --python $pythonVersion python scripts/client_release.py sign `
        --private-key $privateKey `
        --installer $installerPath `
        --platform win64 `
        --version $version
    if ($LASTEXITCODE -ne 0) {
        throw "Client release signing failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Verifying the signed Windows client release..."
uv run --frozen --python $pythonVersion python scripts/client_release.py verify `
    --release-dir $clientDir
if ($LASTEXITCODE -ne 0) {
    throw "Client release verification failed with exit code $LASTEXITCODE"
}

# Prompt for deploy
$answer = if ($DeployOnly) { "y" } else { Read-Host "Deploy client installer to server? (y/n)" }

if ($answer -ne 'y' -and $answer -ne 'Y') {
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

    $remoteBase = $remoteDir.TrimEnd('/')
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $releaseSequence = [Int64]$manifest.release_sequence
    if ($releaseSequence -le 0) {
        throw "Signed client manifest has an invalid release sequence"
    }
    if ($manifest.artifacts.Count -ne 1 -or $manifest.artifacts[0].filename -ne (Split-Path $installerPath -Leaf)) {
        throw "Signed client manifest does not describe the expected Windows installer"
    }

    $remotePlatformDir = "$remoteBase/win64"
    $remoteReleaseDir = "$remotePlatformDir/releases/$releaseSequence"
    $remoteSpecBase = "${remoteUser}@${remoteHost}"
    ssh $remoteSpecBase "if [ -e '$remoteReleaseDir' ]; then exit 17; fi; mkdir -p '$remoteReleaseDir'"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote client release $releaseSequence already exists or could not be created"
    }

    $releaseFiles = @(
        Get-Item -LiteralPath $installerPath
        Get-Item -LiteralPath $manifestPath
        Get-Item -LiteralPath $signaturePath
    )
    foreach ($releaseFile in $releaseFiles) {
        $remotePath = "$remoteReleaseDir/$($releaseFile.Name)"
        Write-Host "Uploading immutable release file: $($releaseFile.Name)"
        scp $releaseFile.FullName "${remoteSpecBase}:$remotePath"
        if ($LASTEXITCODE -ne 0) {
            throw "Client release upload failed for $($releaseFile.Name)"
        }

        $expectedSize = $releaseFile.Length
        $expectedHash = (Get-FileHash -LiteralPath $releaseFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $remoteSize = ssh $remoteSpecBase "stat -c %s '$remotePath'"
        if ($LASTEXITCODE -ne 0 -or [Int64]$remoteSize -ne $expectedSize) {
            throw "Remote size verification failed for $($releaseFile.Name)"
        }
        $remoteHashOutput = ssh $remoteSpecBase "sha256sum '$remotePath'"
        if ($LASTEXITCODE -ne 0) {
            throw "Remote hash verification failed for $($releaseFile.Name)"
        }
        $remoteHash = ($remoteHashOutput -split '\s+')[0].ToLowerInvariant()
        if ($remoteHash -ne $expectedHash) {
            throw "Remote hash mismatch for $($releaseFile.Name)"
        }
    }

    $pointerPath = Join-Path ([System.IO.Path]::GetTempPath()) "parsetrail-client-release-$([guid]::NewGuid().ToString('N')).json"
    try {
        $pointer = @{
            schema_version = 1
            release_sequence = $releaseSequence
        } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText(
            $pointerPath,
            "$pointer`n",
            [System.Text.UTF8Encoding]::new($false)
        )
        $remotePointerPart = "$remotePlatformDir/current-release.json.part"
        scp $pointerPath "${remoteSpecBase}:$remotePointerPart"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not upload the client release pointer"
        }
        ssh $remoteSpecBase "mv '$remotePointerPart' '$remotePlatformDir/current-release.json'"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not activate client release $releaseSequence"
        }
    }
    finally {
        Remove-Item -LiteralPath $pointerPath -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Signed client release $releaseSequence deployed and activated successfully."
} catch {
    Write-Error "ERROR: Deployment failed. $($_.Exception.Message)"
    throw
}

exit 0
