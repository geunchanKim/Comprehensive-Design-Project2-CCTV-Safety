param(
    [ValidateSet('start', 'stop', 'status')][string]$Action = 'status'
)

# Manage only the dedicated, already provisioned .local-demo environment.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$demoRoot = Join-Path $repoRoot '.local-demo'
$settings = Get-Content (Join-Path $demoRoot 'settings.json') -Raw | ConvertFrom-Json
$pgControl = Join-Path $demoRoot 'pg-runtime/pgsql/bin/pg_ctl.exe'
$pgData = Join-Path $demoRoot 'pgdata'
$pythonPath = (Get-Command python).Source

function Get-ManagedProcess([string]$Name, [string]$CommandFragment) {
    $pidFile = Join-Path $demoRoot "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    $managedId = 0
    if (-not [int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$managedId)) {
        throw "Invalid process record: $Name"
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $managedId"
    if ($null -eq $process) { return $null }
    if ($process.ExecutablePath -ne $pythonPath -or
        -not $process.CommandLine.Contains($CommandFragment)) {
        throw "Process record no longer belongs to this demo: $Name. No process was stopped."
    }
    return $process
}

function Start-ManagedPython([string]$Name, [string[]]$Arguments) {
    $process = Start-Process -FilePath $pythonPath -ArgumentList $Arguments `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $demoRoot "$Name.stdout.log") `
        -RedirectStandardError (Join-Path $demoRoot "$Name.stderr.log")
    $process.Id | Set-Content (Join-Path $demoRoot "$Name.pid")
}

function Wait-Http([string]$Url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 200
    }
    throw "Service did not become ready: $Url. Inspect .local-demo logs."
}

$apiFragment = "backend.main:app --host 127.0.0.1 --port $($settings.api_port)"
$diagnosticFragment = '.local-demo/serve.py'
if ($Action -eq 'stop') {
    # Validate all PID records before stopping anything; never stop unrelated services.
    $owned = @((Get-ManagedProcess 'diagnostic' $diagnosticFragment),
               (Get-ManagedProcess 'api' $apiFragment))
    foreach ($process in $owned) {
        if ($null -ne $process) { Stop-Process -Id $process.ProcessId }
    }
    & $pgControl -D $pgData status *> $null
    if ($LASTEXITCODE -eq 0) {
        & $pgControl -D $pgData -m fast -w stop
        if ($LASTEXITCODE -ne 0) { throw 'Demo database shutdown failed.' }
    }
    Write-Output 'Dedicated demo stopped. Database files were preserved.'
    exit
}

if ($Action -eq 'start') {
    & $pgControl -D $pgData status *> $null
    if ($LASTEXITCODE -ne 0) {
        # Wait only for pg_ctl, not the entire PostgreSQL process tree.
        $pgProcess = Start-Process -FilePath $pgControl -WindowStyle Hidden -PassThru `
            -ArgumentList @('-D', "`"$pgData`"", '-l', "`"$(Join-Path $demoRoot 'postgres.log')`"",
                            '-o', "`"-p $($settings.pg_port) -h 127.0.0.1`"", '-w', 'start')
        $pgProcess.WaitForExit()
        if ($pgProcess.ExitCode -ne 0) { throw 'Demo PostgreSQL failed to start.' }
    }
    $apiProcess = Get-ManagedProcess 'api' $apiFragment
    if ($null -eq $apiProcess) {
        $variables = @{
            DATABASE_URL = $settings.database_url
            ENABLE_RISK_ANALYSIS = 'true'
            DASHBOARD_SESSION_ID = $settings.session_id
            DASHBOARD_CALIBRATION_PROFILE = $settings.calibration_profile
            DASHBOARD_ALGORITHM = $settings.algorithm
            APP_COMMIT_SHA = (git -C $repoRoot rev-parse --short HEAD)
        }
        $previous = @{}
        try {
            foreach ($name in $variables.Keys) {
                $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
                [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
            }
            Start-ManagedPython 'api' @('-m', 'uvicorn', 'backend.main:app', '--host',
                                       '127.0.0.1', '--port', "$($settings.api_port)")
        } finally {
            foreach ($name in $previous.Keys) {
                [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
            }
        }
    }
    Wait-Http "http://127.0.0.1:$($settings.api_port)/health/db"
    if ($null -eq (Get-ManagedProcess 'diagnostic' $diagnosticFragment)) {
        Start-ManagedPython 'diagnostic' @('.local-demo/serve.py')
    }
    Wait-Http 'http://127.0.0.1:8002/'
}

& $pgControl -D $pgData status
foreach ($url in @("http://127.0.0.1:$($settings.api_port)/health/db", 'http://127.0.0.1:8002/')) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 3
        Write-Output "$url : HTTP $($response.StatusCode)"
    } catch { Write-Output "$url : unavailable" }
}
