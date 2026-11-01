$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'logs/server.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'Image Studio is not running.'; exit }
$record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if ($null -eq $process -or $process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$record.started).ToUniversalTime().Ticks) {
    Write-Host 'The recorded Image Studio server is no longer running.'
    exit
}
$queue = Invoke-RestMethod 'http://127.0.0.1:8193/queue' -TimeoutSec 5
if ($queue.queue_running.Count -gt 0 -or $queue.queue_pending.Count -gt 0) {
    throw 'An image job is active or queued. Finish or cancel it in ComfyUI before stopping Image Studio.'
}
Stop-Process -Id $process.Id
Write-Host 'Image Studio stopped.'
