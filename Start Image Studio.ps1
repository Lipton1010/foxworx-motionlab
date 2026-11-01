param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
foreach ($folder in 'logs','user','input','output','temp') { New-Item -ItemType Directory -Path (Join-Path $studioRoot $folder) -Force | Out-Null }
$pidFile = Join-Path $studioRoot 'logs/server.json'
$url = 'http://127.0.0.1:8193'
$running = $false
if (Test-Path -LiteralPath $pidFile) {
    $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    $running = $null -ne $process -and $process.StartTime.ToUniversalTime().Ticks -eq ([datetime]$record.started).ToUniversalTime().Ticks
}
if (-not $running) {
    if (Get-NetTCPConnection -LocalPort 8193 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 8193 is already in use by another process. Image Studio was not started.'
    }
    $python = Join-Path $studioRoot 'runtime/ComfyUI_windows_portable/python_embeded/python.exe'
    if (-not (Test-Path -LiteralPath $python) -and -not (Test-Path -LiteralPath (Join-Path $studioRoot 'portable.json'))) { $python = 'D:\ComfyUI\python_embeded\python.exe' }
    if (-not (Test-Path -LiteralPath $python)) { throw 'The local engine is not installed. Close Image Studio and run Setup.cmd in its folder.' }
    $logStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $process = Start-Process -FilePath $python -ArgumentList '-s', ('"' + (Join-Path $studioRoot 'launch.py') + '"') -WorkingDirectory $studioRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $studioRoot "logs/server-$logStamp.out.log") -RedirectStandardError (Join-Path $studioRoot "logs/server-$logStamp.err.log")
    @{pid=$process.Id; started=$process.StartTime.ToUniversalTime().ToString('o'); url=$url} | ConvertTo-Json | Set-Content -LiteralPath $pidFile
}
$ready = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if ($process.HasExited) { throw 'Image Studio exited during startup. See the newest file in logs.' }
    try {
        $null = Invoke-RestMethod "$url/system_stats" -TimeoutSec 2
        $ready = $true
        break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { throw 'Image Studio is still starting. Check logs before trying again.' }
Write-Host "Image Studio is ready at $url"
if (-not $NoBrowser) { Start-Process $url }
