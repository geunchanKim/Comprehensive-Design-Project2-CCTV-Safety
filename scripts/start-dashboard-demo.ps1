param(
    [Parameter(Mandatory = $true)][string]$DatabaseUrl,
    [Parameter(Mandatory = $true)][string]$SessionId,
    [ValidateSet('basic', 'precise')][string]$CalibrationProfile = 'precise',
    [string]$Algorithm = 'improved',
    [ValidateRange(1024, 65535)][int]$Port = 8001,
    [string]$BindAddress = '127.0.0.1'
)

# Run in a dedicated terminal with a dedicated demo database.
$ErrorActionPreference = 'Stop'
if ($DatabaseUrl -notmatch '^postgresql(\+psycopg2)?://') {
    throw 'Use a dedicated PostgreSQL demo database; full SQLite migrations are unsupported.'
}
if ([string]::IsNullOrWhiteSpace($SessionId) -or $SessionId.Length -gt 128) {
    throw 'SessionId must contain 1-128 characters.'
}
$demoVariables = @{
    DATABASE_URL = $DatabaseUrl
    ENABLE_RISK_ANALYSIS = 'true'
    DASHBOARD_SESSION_ID = $SessionId
    DASHBOARD_CALIBRATION_PROFILE = $CalibrationProfile
    DASHBOARD_ALGORITHM = $Algorithm
}
$previousValues = @{}
foreach ($name in $demoVariables.Keys) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location (Join-Path $PSScriptRoot '../backend')
try {
    foreach ($name in $demoVariables.Keys) {
        [Environment]::SetEnvironmentVariable($name, $demoVariables[$name], 'Process')
    }
    python -c "from api import algorithm_features; import os; algorithm_features(os.environ['DASHBOARD_ALGORITHM'])"
    if ($LASTEXITCODE -ne 0) { throw 'Invalid algorithm or missing backend dependencies.' }
    python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Demo database migration failed; server was not started.' }
    Write-Host "Demo API: http://${BindAddress}:${Port}/docs"
    Write-Host "Condition: $SessionId / $CalibrationProfile / $Algorithm"
    python -m uvicorn main:app --host $BindAddress --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Demo server exited with an error.' }
}
finally {
    Pop-Location
    foreach ($name in $demoVariables.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousValues[$name], 'Process')
    }
}
