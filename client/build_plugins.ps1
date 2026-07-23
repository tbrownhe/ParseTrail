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

$required = @{
    PLUGINS_DIR = $pluginsDir
    PLUGIN_SIGNING_KEY = $privateKey
    REMOTE_USER = $remoteUser
    REMOTE_HOST = $remoteHost
    REMOTE_PLUGINS_DIR = $remoteDir
}
$missing = @($required.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($missing.Count -gt 0) {
    throw "Missing required environment variables: $($missing -join ', ')"
}

Push-Location $PSScriptRoot
try {
    Write-Host "Synchronizing the locked client environment..."
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }

    Write-Host "Running client regression tests before release..."
    uv run --frozen pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Client tests failed with exit code $LASTEXITCODE"
    }

    Write-Host "Compiling plugins..."
    uv run --frozen python src/parsetrail/build_plugins.py
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin compilation failed with exit code $LASTEXITCODE"
    }

    Write-Host "Signing the complete plugin catalog..."
    uv run --frozen python scripts/plugin_release.py sign `
        --private-key $privateKey `
        --plugin-dir $pluginsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin signing failed with exit code $LASTEXITCODE"
    }

    Write-Host "Verifying the release using only the bundled public key..."
    uv run --frozen python scripts/plugin_release.py verify --plugin-dir $pluginsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin release verification failed with exit code $LASTEXITCODE"
    }

    $answer = Read-Host "Deploy the signed plugin release to the server? (y/n)"
    if ($answer -notin @("y", "Y")) {
        Write-Host "Signed release retained locally; deployment skipped."
        exit 0
    }

    $manifestPath = Join-Path $pluginsDir "plugin-manifest.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $releaseSequence = [Int64]$manifest.release_sequence
    if ($releaseSequence -le 0) {
        throw "Signed manifest has an invalid release sequence"
    }

    $releaseFiles = @(
        Get-ChildItem -LiteralPath $pluginsDir -File -Filter "*.pyc"
        Get-Item -LiteralPath $manifestPath
        Get-Item -LiteralPath (Join-Path $pluginsDir "plugin-manifest.sig")
    )
    $remoteBase = $remoteDir.TrimEnd("/")
    $remoteReleaseDir = "$remoteBase/releases/$releaseSequence"
    $remoteSpecBase = "${remoteUser}@${remoteHost}"

    Write-Host "Creating immutable remote release directory $releaseSequence..."
    ssh $remoteSpecBase "mkdir -p '$remoteReleaseDir'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the remote plugin release directory"
    }

    foreach ($releaseFile in $releaseFiles) {
        $remotePath = "$remoteReleaseDir/$($releaseFile.Name)"
        $remoteSpec = "${remoteUser}@${remoteHost}:$remotePath"
        Write-Host "Uploading signed release file: $($releaseFile.Name)"
        scp $releaseFile.FullName $remoteSpec
        if ($LASTEXITCODE -ne 0) {
            throw "Upload failed for $($releaseFile.Name)"
        }
    }

    $pointerPath = Join-Path ([System.IO.Path]::GetTempPath()) "parsetrail-current-release-$([guid]::NewGuid().ToString('N')).json"
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
        $remotePointerPart = "$remoteBase/current-release.json.part"
        scp $pointerPath "${remoteSpecBase}:$remotePointerPart"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not upload the plugin release pointer"
        }
        ssh $remoteSpecBase "mv '$remotePointerPart' '$remoteBase/current-release.json'"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not activate plugin release $releaseSequence"
        }
    }
    finally {
        Remove-Item -LiteralPath $pointerPath -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Signed plugin release deployed successfully."
}
finally {
    Pop-Location
}
