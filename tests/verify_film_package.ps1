param([Parameter(Mandatory)][string]$PackagePath)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$package=[IO.Path]::GetFullPath($PackagePath)
$verification=Join-Path $repo ('temp/film-implementation/extraction-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $verification -Force | Out-Null
$archive=Join-Path $verification 'portable.zip'
$seven=Join-Path $env:ProgramFiles '7-Zip/7z.exe'
Push-Location (Split-Path -Parent $package)
try { & $seven a -tzip $archive ([IO.Path]::GetFileName($package)) -mx=1 -bso0 -bsp0; if($LASTEXITCODE){throw 'Package archive creation failed.'} }
finally { Pop-Location }
& $seven x $archive ('-o'+(Join-Path $verification 'fresh')) -bso0 -bsp0
if($LASTEXITCODE){throw 'Fresh package extraction failed.'}
$fresh=Join-Path $verification ('fresh/'+[IO.Path]::GetFileName($package))
$count=0
foreach($line in [IO.File]::ReadAllLines((Join-Path $fresh 'SHA256SUMS.txt'))){
    $expected=$line.Substring(0,64); $relative=$line.Substring(66)
    $actual=(Get-FileHash -LiteralPath (Join-Path $fresh $relative)).Hash.ToLower()
    if($actual -ne $expected){throw ('Package manifest mismatch: '+$relative)}
    $count++
}
function Invoke-Film([hashtable]$Request){
    $inputFile=Join-Path $verification ('command-'+[guid]::NewGuid().ToString('N')+'.json')
    [IO.File]::WriteAllText($inputFile,($Request | ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
    $reply=Get-Content -LiteralPath $inputFile -Raw | & (Join-Path $fresh 'runtime/production-python/python.exe') -u (Join-Path $fresh 'desktop/production_service.py') $fresh
    if($LASTEXITCODE){throw ('Packaged command failed: '+$reply)}
    $result=$reply | ConvertFrom-Json
    if(!$result.ok){throw ('Packaged command did not succeed: '+$reply)}
    return $result.result
}
$readiness=Invoke-Film @{version=1;operation='readiness';request_id='fresh-readiness';payload=@{}}
if(Test-Path -LiteralPath (Join-Path $fresh 'runtime/media')){throw 'Media binaries must not ship in the core archive.'}
if(!(Test-Path -LiteralPath (Join-Path $fresh 'portable/InstallMedia.ps1'))){throw 'Optional media setup is missing.'}
$created=Invoke-Film @{version=1;operation='create';request_id='fresh-create';payload=@{title='FRESH EXTRACTION SYNTHETIC FIXTURE'}}
$saved=Invoke-Film @{version=1;operation='shot-add';request_id='fresh-shot';project_id=$created.id;expected_revision=$created.revision;payload=@{}}
if($saved.project.shots.Count -ne 1){throw 'Fresh shared-interface persistence failed.'}
$graphRequest=@{root=$fresh;kind='video';request=@{Prompt='Synthetic graph-only check';Negative='';Seed=1;Width=768;Height=448;Seconds=5;Model='minimax_h3_fl2va_pruned_int8_convrot.safetensors'}} | ConvertTo-Json -Depth 5
$graph=$graphRequest | & (Join-Path $fresh 'app/graph-host/ImageStudio.GraphHost.exe') | ConvertFrom-Json
if($LASTEXITCODE -ne 0 -or !$graph.ok -or $graph.graph.save.class_type -ne 'SaveVideo'){throw 'Fresh graph host/template/root-resolution failed.'}
$report=@{fresh_root=$fresh;files_verified=$count;engine_installed=(Test-Path -LiteralPath (Join-Path $fresh 'runtime/ComfyUI_windows_portable'));readiness=$readiness;project=$created.id;graph_host=$true;scope='Real extracted helpers and graph builder; no inference or generated-film quality claim.'}
$evidence=Join-Path $repo 'temp/film-implementation/evidence'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'portable-extraction.json')
$report | ConvertTo-Json -Depth 3
