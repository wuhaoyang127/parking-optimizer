# Parking public deployment - step 2: start driver + console + cloudflared tunnel
# Prereq: setup-tunnel.ps1 already run (tunnel created and bound to driver/console subdomains)
# Usage: powershell -ExecutionPolicy Bypass -File .\start-public.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'integration.local.json') -Raw | ConvertFrom-Json
$env:PARKING_PUBLISH_TOKEN    = $config.publish_token
$env:PARKING_ADMIN_TOKEN      = $config.admin_token
$env:PARKING_CONSOLE_PASSWORD = $config.console_password
# Console (local) calls driver API over loopback, bypassing the HTTPS-required check
$env:PARKING_DRIVER_API_URL   = 'http://127.0.0.1:8000'
# "Open driver" button in console points to public URL
$env:PARKING_DRIVER_WEB_URL   = 'https://driver.wuhaoyang127.top'
$env:PARKING_RESEARCH_ROOT    = Join-Path $PSScriptRoot 'research'
$env:PARKING_RESEARCH_PYTHON  = Join-Path $PSScriptRoot 'research/.venv/Scripts/python.exe'

$driverPython   = Join-Path $PSScriptRoot 'driver/.venv/Scripts/python.exe'
$researchPython = Join-Path $PSScriptRoot 'research/.venv/Scripts/python.exe'
$cf = (Get-Command cloudflared -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath 'driver/apps/web/dist/index.html')) {
    throw 'Frontend not built. Run: npm --prefix driver/apps/web run build'
}

# Port check
foreach ($port in @(8000, 8501)) {
    $probe = [Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1', $port); throw "Port $port is occupied; stop its owner first." }
    catch [Net.Sockets.SocketException] { }
    finally { $probe.Dispose() }
}

$children = @()
try {
    # 1) Driver: serve.py single-origin (FastAPI + frontend dist), loopback only
    $driverArgs = '-m uvicorn serve:app --app-dir driver --host 127.0.0.1 --port 8000 --http h11'
    $children += Start-Process -FilePath $driverPython -ArgumentList $driverArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru

    # 2) Console: integration_console.py (Streamlit, password login), loopback only
    $consoleArgs = '-m streamlit run integration_console.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false'
    $children += Start-Process -FilePath $researchPython -ArgumentList $consoleArgs -WorkingDirectory (Join-Path $PSScriptRoot 'research') -WindowStyle Hidden -PassThru

    # 3) cloudflared tunnel: driver/console subdomains forward to loopback
    $children += Start-Process -FilePath $cf -ArgumentList @('tunnel','run','parking') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru

    # Wait for both local services
    $deadline = (Get-Date).AddSeconds(60)
    foreach ($url in @('http://127.0.0.1:8000/api/v2/health','http://127.0.0.1:8501/_stcore/health')) {
        do {
            if (@($children | Where-Object HasExited).Count) { throw 'A service exited during startup.' }
            try {
                $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
                if ($r.StatusCode -eq 200) { break }
            } catch { }
            if ((Get-Date) -gt $deadline) { throw "Startup timed out: $url" }
            Start-Sleep -Milliseconds 250
        } while ($true)
    }

    Write-Host ''
    Write-Host 'Started:'
    Write-Host '  Driver: https://driver.wuhaoyang127.top'
    Write-Host '  Console: https://console.wuhaoyang127.top'
    Write-Host 'Press Ctrl+C to stop.'
    while ($true) {
        if (@($children | Where-Object HasExited).Count) { throw 'A service stopped; shutting down.' }
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($child in $children) {
        if (-not $child.HasExited) { Stop-Process -Id $child.Id -ErrorAction SilentlyContinue }
    }
}
