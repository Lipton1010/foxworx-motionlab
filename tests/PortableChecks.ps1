$ErrorActionPreference='Stop'
$repoRoot=Split-Path $PSScriptRoot
. (Join-Path $repoRoot 'portable/Common.ps1')
$catalog=Get-Content (Join-Path $repoRoot 'portable/catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$laptop=[pscustomobject]@{RamGB=32;VramGB=16;Driver='580.88';X64=$true}
$script:checks=0
function Check($pass,$message){if(-not $pass){throw "FAIL: $message"}; $script:checks++; Write-Output "PASS: $message"}
$selected=@('qwen')
[string[]]$restored=(ConvertTo-Json -InputObject $selected) | ConvertFrom-Json
Check ($restored.Count -eq 1 -and $restored[0] -is [string] -and $restored[0] -eq 'qwen') 'Setup selection remains plain model IDs across the background-process JSON boundary'
foreach($id in 'qwen','krea','ltx','rewriters','moss','minimax') {
    Check ([string]::IsNullOrEmpty((Get-StudioCompatibility ($catalog.bundles | Where-Object id -eq $id) $laptop))) "$id is offered on the target 16 GB VRAM / 32 GB RAM laptop"
}
$qwen=$catalog.bundles | Where-Object id -eq 'qwen'
Check ($qwen.title.Contains([char]0x2014)) 'UTF-8 catalog names survive Windows PowerShell 5.1'
$laptop.Driver='560.94'
Check ((Get-StudioCompatibility $qwen $laptop) -match 'driver') 'Old driver produces an actionable requirement'
$laptop.Driver='580.88';$laptop.VramGB=0
Check ((Get-StudioCompatibility $qwen $laptop) -match 'NVIDIA') 'Missing GPU is reported before downloads'
$laptop.VramGB=16
$plan=@(Get-StudioPlan $catalog @('qwen','rewriters') $laptop)
Check ($plan.Count -eq 11) 'Selected plan includes exactly the engine and selected model dependencies'
try {Get-StudioPlan $catalog @('unknown') $laptop | Out-Null; throw 'Unknown selection was accepted'} catch {Check ($_.Exception.Message -match 'Unknown download choice') 'Invalid selection cannot trigger downloads'}
$laptop.RamGB=16
try {Get-StudioPlan $catalog @('moss') $laptop | Out-Null; throw 'Incompatible selection was accepted'} catch {Check ($_.Exception.Message -match '32 GB') 'Worker enforces hardware rules independently of the UI'}
$laptop.RamGB=32
try {Get-StudioPath $repoRoot '../escape' | Out-Null; throw 'Traversal was accepted'} catch {Check ($_.Exception.Message -match 'Invalid package path') 'Downloads cannot escape the package folder'}
foreach($entry in @($catalog.engine)+@($catalog.bundles | ForEach-Object files)) {
    Check ($entry.sha256 -match '^[a-f0-9]{64}$' -and $entry.bytes -gt 0 -and ([uri]$entry.url).Scheme -eq 'https') "Pinned size/checksum for $($entry.path)"
}
foreach($script in Get-ChildItem (Join-Path $repoRoot 'portable') -Filter *.ps1) {
    $errors=$null
    [Management.Automation.Language.Parser]::ParseFile($script.FullName,[ref]$null,[ref]$errors) | Out-Null
    Check ($errors.Count -eq 0) "$($script.Name) parses in this PowerShell version"
}
$testRoot=Join-Path $repoRoot ('temp/portable-check-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$file=Join-Path $testRoot 'verified.txt'
try {
    $worker=Start-Process powershell.exe -ArgumentList '-NoProfile','-Command','exit 0' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $testRoot 'worker.out') -RedirectStandardError (Join-Path $testRoot 'worker.err')
    $null=$worker.Handle
    $worker.WaitForExit()
    Check ($worker.ExitCode -eq 0) 'Redirected background installer retains its successful exit code'
    $worker.Dispose()
    [IO.File]::WriteAllText($file,'test')
    $entry=[pscustomobject]@{path='verified.txt';bytes=4;sha256=(Get-FileHash $file).Hash;url='https://huggingface.co/unused-by-verified-cache'}
    $output=@(Save-StudioDownload $entry $testRoot)
    Check ($output[-1] -eq 'Verified verified.txt') 'Verified cached downloads are reused without network access'
    $entry.path='resume.txt'
    $partial=Join-Path $testRoot 'resume.txt.partial'
    [IO.File]::WriteAllText($partial,'test')
    function curl.exe { throw 'Unexpected network request for a fully downloaded partial file' }
    $output=@(Save-StudioDownload $entry $testRoot)
    Check ((Test-Path (Join-Path $testRoot 'resume.txt')) -and -not (Test-Path $partial)) 'An interruption after download completion resumes by verifying the complete partial file'
} finally {
    foreach($name in 'verified.txt','resume.txt','resume.txt.partial','worker.out','worker.err') { $target=Join-Path $testRoot $name; if(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target} }
    Remove-Item -LiteralPath $testRoot
}
Write-Output "Passed $script:checks portable setup checks."
