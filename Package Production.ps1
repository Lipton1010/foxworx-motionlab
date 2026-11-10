param([Parameter(Mandatory)][string]$Destination, [switch]$SelfContained)
$ErrorActionPreference='Stop'
$productionPackage = [IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath (Join-Path $productionPackage 'runtime/media')){
    throw 'Use a clean staging directory: media runtimes are optional upstream downloads and must not be bundled.'
}
New-Item -ItemType Directory -Path (Join-Path $productionPackage 'desktop'),(Join-Path $productionPackage 'app/graph-host'),(Join-Path $productionPackage 'runtime/custom_nodes/image-studio-av'),(Join-Path $productionPackage 'runtime/production-python'),(Join-Path $productionPackage 'licenses') -Force | Out-Null
if($productionPackage -ne [IO.Path]::GetFullPath($PSScriptRoot)){
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'desktop') -File | Where-Object { $_.Name -like 'production_*.py' -or $_.Name -like 'production_*.json' -or $_.Name -in 'rewrite_prompt.py','prompt_profiles.py','FILM_PROCESS.md','PRODUCTION.md' } | Copy-Item -Destination (Join-Path $productionPackage 'desktop')
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'runtime/custom_nodes/image-studio-av') -File -Filter '*.py' | Copy-Item -Destination (Join-Path $productionPackage 'runtime/custom_nodes/image-studio-av')
}
$hostArguments=@('publish',(Join-Path $PSScriptRoot 'graph-host/GraphHost.csproj'),'-c','Release','-r','win-x64','--self-contained',($SelfContained.IsPresent.ToString().ToLower()),'--artifacts-path',(Join-Path $PSScriptRoot 'temp/film-package-artifacts'),'-p:NuGetAudit=false','-p:RestoreIgnoreFailedSources=true',('-p:RestorePackagesPath='+(Join-Path $PSScriptRoot 'temp/portable-nuget')),'-p:RestoreSources=https://api.nuget.org/v3/index.json','-o',(Join-Path $productionPackage 'app/graph-host'))
& dotnet @hostArguments
if($LASTEXITCODE -ne 0){throw 'Production graph host publish failed.'}
$pythonSource=Join-Path $PSScriptRoot 'runtime/ComfyUI_windows_portable/python_embeded'
if(!(Test-Path -LiteralPath (Join-Path $pythonSource 'python.exe'))){$pythonSource='D:/ComfyUI/python_embeded'}
if(!(Test-Path -LiteralPath (Join-Path $pythonSource 'python.exe'))){throw 'An existing supported embedded Python is required to package the CPU film tools.'}
$pythonTarget=Join-Path $productionPackage 'runtime/production-python'
$pythonManifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'portable/python-3.13.14-files.json') -Raw | ConvertFrom-Json
foreach($file in $pythonManifest.files){
    $source=Join-Path $pythonSource $file.file
    if(!(Test-Path -LiteralPath $source) -or (Get-FileHash -LiteralPath $source).Hash.ToLower() -ne $file.sha256){throw ('Existing embedded Python differs from the reviewed official 3.13.14 file: '+$file.file)}
    Copy-Item -LiteralPath $source -Destination $pythonTarget
}
$zip=Get-ChildItem -LiteralPath $pythonTarget -Filter 'python*.zip' | Select-Object -First 1
if(!$zip){throw 'Embedded Python standard-library ZIP is missing.'}
$pth=Join-Path $pythonTarget ($zip.BaseName+'._pth')
[IO.File]::WriteAllLines($pth,@($zip.Name,'.','import site'),[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'portable/licenses/Python-3.13.14-embedded.txt') -Destination (Join-Path $productionPackage 'licenses/Python.txt')
# Media executables are supplied only through an explicit upstream download.
# Never copy developer/Chocolatey binaries or mismatched notices into a release.
$runtimeFiles=@(Get-ChildItem -LiteralPath $pythonTarget -File | ForEach-Object { [ordered]@{path=[IO.Path]::GetRelativePath($productionPackage,$_.FullName);sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLower();bytes=$_.Length} })
@{python='3.13.14 existing embedded Windows runtime; all 30 binary/stdlib files match the official distribution';pythonSource=$pythonManifest.source;pythonArchiveSha256=$pythonManifest.archive_sha256;ffmpeg='Not bundled; user-consented upstream download through Setup > Media tools';ffmpegSource='portable/media-runtime.json';files=$runtimeFiles} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $productionPackage 'production-runtime-manifest.json')
Write-Output ('PRODUCTION_HELPERS='+$productionPackage)
