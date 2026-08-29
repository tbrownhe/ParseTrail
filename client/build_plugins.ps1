$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $repositoryRoot ".env"

if (-not (Test-Path $envFile)) {
    throw "Missing environment file: $envFile"
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$pluginsDir = $env:PLUGINS_DIR
$privateKey = $env:PLUGIN_SIGNING_KEY
$remoteUser = $env:REMOTE_USER
$remoteHost = $env:REMOTE_HOST
$remoteDir = $env:REMOTE_PLUGINS_DIR
$pythonVersionFile = Join-Path $PSScriptRoot ".python-version"

$required = @{
    PLUGINS_DIR = $pluginsDir
    PLUGIN_SIGNING_KEY = $privateKey
}
$missing = @($required.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($missing.Count -gt 0) {
    throw "Missing required environment variables: $($missing -join ', ')"
}
if (-not (Test-Path -LiteralPath $pythonVersionFile -PathType Leaf)) {
    throw "Missing Python version file: $pythonVersionFile"
}
$pythonVersion = (Get-Content -LiteralPath $pythonVersionFile -Raw).Trim()
if (-not $pythonVersion) {
    throw "Python version file is empty: $pythonVersionFile"
}

Push-Location $PSScriptRoot
try {
    Write-Host "Synchronizing the locked client test environment with Python $pythonVersion..."
    uv sync --extra dev --frozen --python $pythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }

    Write-Host "Running client regression tests before release..."
    uv run --extra dev --frozen --python $pythonVersion pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Client tests failed with exit code $LASTEXITCODE"
    }

    Write-Host "Compiling plugins..."
    uv run --frozen --python $pythonVersion python src/parsetrail/build_plugins.py
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin compilation failed with exit code $LASTEXITCODE"
    }

    Write-Host "Signing the complete plugin catalog..."
    uv run --frozen --python $pythonVersion python scripts/plugin_release.py sign `
        --private-key $privateKey `
        --plugin-dir $pluginsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin signing failed with exit code $LASTEXITCODE"
    }

    Write-Host "Verifying the release using only the bundled public key..."
    uv run --frozen --python $pythonVersion python scripts/plugin_release.py verify --plugin-dir $pluginsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin release verification failed with exit code $LASTEXITCODE"
    }

    $answer = Read-Host "Deploy the signed plugin release to the server? (y/n)"
    if ($answer -notin @("y", "Y")) {
        Write-Host "Signed release retained locally; deployment skipped."
        exit 0
    }

    $remoteRequired = @{
        REMOTE_USER = $remoteUser
        REMOTE_HOST = $remoteHost
        REMOTE_PLUGINS_DIR = $remoteDir
    }
    $remoteMissing = @(
        $remoteRequired.GetEnumerator() |
            Where-Object { -not $_.Value } |
            ForEach-Object { $_.Key }
    )
    if ($remoteMissing.Count -gt 0) {
        throw "Missing deployment environment variables: $($remoteMissing -join ', ')"
    }

    uv run --frozen --python $pythonVersion python scripts/immutable_publish.py `
        --release-dir $pluginsDir `
        --manifest plugin-manifest.json `
        --signature plugin-manifest.sig `
        --remote "${remoteUser}@${remoteHost}" `
        --remote-root $remoteDir
    if ($LASTEXITCODE -ne 0) {
        throw "Immutable plugin publication failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
