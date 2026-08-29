param(
    [Parameter(Mandatory = $true)]
    [string]$PluginsDir,
    [Parameter(Mandatory = $true)]
    [string]$SigningKey,
    [Parameter(Mandatory = $true)]
    [string]$SourceTag,
    [switch]$Publish,
    [string]$RemoteUser,
    [string]$RemoteHost,
    [string]$RemotePluginsDir
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PluginsDir -PathType Container)) {
    throw "PluginsDir does not exist or is not a directory: $PluginsDir"
}
if (-not (Test-Path -LiteralPath $SigningKey -PathType Leaf)) {
    throw "SigningKey does not exist or is not a file: $SigningKey"
}
$pluginsDirPath = (Resolve-Path -LiteralPath $PluginsDir).Path
$signingKeyPath = (Resolve-Path -LiteralPath $SigningKey).Path
$pythonVersionFile = Join-Path $PSScriptRoot ".python-version"
if (-not (Test-Path -LiteralPath $pythonVersionFile -PathType Leaf)) {
    throw "Missing Python version file: $pythonVersionFile"
}
$pythonVersion = (Get-Content -LiteralPath $pythonVersionFile -Raw).Trim()
if (-not $pythonVersion) {
    throw "Python version file is empty: $pythonVersionFile"
}

Push-Location $PSScriptRoot
try {
    Write-Host "Validating clean, tagged release source..."
    $sourceJson = uv run --frozen --python $pythonVersion python scripts/release_source.py plugins `
        --tag $SourceTag
    if ($LASTEXITCODE -ne 0) {
        throw "Release source validation failed with exit code $LASTEXITCODE"
    }
    $releaseSource = $sourceJson | ConvertFrom-Json

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

    Write-Host "Compiling the complete plugin catalog in the pinned interpreter..."
    uv run --frozen --python $pythonVersion python src/parsetrail/build_plugins.py `
        --output-dir $pluginsDirPath
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin compilation failed with exit code $LASTEXITCODE"
    }

    Write-Host "Signing the complete plugin catalog..."
    uv run --frozen --python $pythonVersion python scripts/plugin_release.py sign `
        --private-key $signingKeyPath `
        --plugin-dir $pluginsDirPath `
        --source-commit $releaseSource.source_commit
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin signing failed with exit code $LASTEXITCODE"
    }

    Write-Host "Verifying the release using only the bundled public key..."
    uv run --frozen --python $pythonVersion python scripts/plugin_release.py verify `
        --plugin-dir $pluginsDirPath
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin release verification failed with exit code $LASTEXITCODE"
    }

    Write-Host "Recording checksums and release-tool versions..."
    uv run --frozen --python $pythonVersion python scripts/release_inventory.py `
        --release-dir $pluginsDirPath `
        --source-commit $releaseSource.source_commit `
        --source-tag $releaseSource.source_tag `
        --kind plugins `
        --platform python-$pythonVersion `
        --packager none
    if ($LASTEXITCODE -ne 0) {
        throw "Release inventory generation failed with exit code $LASTEXITCODE"
    }

    if (-not $Publish) {
        Write-Host "Signed plugin dry run completed; publication skipped."
        exit 0
    }
    if (-not $RemoteUser -or -not $RemoteHost -or -not $RemotePluginsDir) {
        throw "RemoteUser, RemoteHost, and RemotePluginsDir are required with -Publish"
    }

    uv run --frozen --python $pythonVersion python scripts/immutable_publish.py `
        --release-dir $pluginsDirPath `
        --manifest plugin-manifest.json `
        --signature plugin-manifest.sig `
        --inventory release-inventory.json `
        --remote "${RemoteUser}@${RemoteHost}" `
        --remote-root $RemotePluginsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Immutable plugin publication failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
