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
$pluginsDir      = $env:PLUGINS_DIR
$remoteUser      = $env:REMOTE_USER
$remoteHost      = $env:REMOTE_HOST
$remoteDir       = $env:REMOTE_PLUGINS_DIR

if (-not $condaEnv -or -not $pluginsDir -or -not $remoteUser -or -not $remoteHost -or -not $remoteDir) {
    Write-Error "One or more required environment variables are missing. Please check $envFile."
    exit 1
}

# --- Paths -------------------------------------------------------------------
$buildScript = Join-Path $PSScriptRoot "src\parsetrail\build_plugins.py"

# --- Activate conda env and build plugins ------------------------------------
try {
    Write-Host "Activating conda environment '$condaEnv'..."
    conda activate $condaEnv
} catch {
    Write-Error "ERROR: Failed to activate conda environment '$condaEnv'."
    exit 1
}

try {
    if (-not (Test-Path $buildScript)) {
        Write-Error "Build script not found at $buildScript"
        throw
    }

    Write-Host "Building plugins using $buildScript ..."
    python $buildScript

    if (-not (Test-Path $pluginsDir)) {
        Write-Error "Plugins directory not found at $pluginsDir after build."
        throw
    }

} catch {
    Write-Error "ERROR: Plugin build failed. $($_.Exception.Message)"
    throw
}
finally {
    try {
        Write-Host "Deactivating conda environment..."
        conda deactivate
    } catch {
        # ignore
    }
}


# --- Deploy plugins to server ------------------------------------------------
# Prompt for deploy
$answer = Read-Host "Deploy plugins to server? (y/n)"

if ($answer -ne 'y' -and $answer -ne 'Y') {
    Write-Host "Aborted."
    exit 1
}

try {
    Write-Host "Starting plugin deployment..."

    if (-not (Test-Path $pluginsDir)) {
        Write-Error "Local plugins directory not found: $pluginsDir"
        exit 1
    }

    $remoteBase = $remoteDir.TrimEnd('/')

    Get-ChildItem -Path $pluginsDir -File | ForEach-Object {
        $localPath  = $_.FullName
        $fileName   = $_.Name
        $remotePath = "$remoteBase/$fileName"

        Write-Host "Syncing: $localPath -> $remotePath"

        # Avoid PowerShell parsing '$var:' as a drive reference
        $remoteSpec = "${remoteUser}@${remoteHost}:$remotePath"

        scp $localPath $remoteSpec
    }

    Write-Host "Plugin deployment completed successfully."
} catch {
    Write-Error "ERROR: Deployment failed. $($_.Exception.Message)"
    throw
}

pause
exit 0
