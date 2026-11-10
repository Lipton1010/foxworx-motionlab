param([string]$OutputDirectory, [switch]$NoArchive)
$ErrorActionPreference='Stop'
$studioRoot=$PSScriptRoot
if(-not $OutputDirectory){$OutputDirectory=Join-Path $studioRoot 'dist'}
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
$env:DOTNET_CLI_HOME=Join-Path $studioRoot 'temp/sandbox-dotnet'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$stage=Join-Path $studioRoot ('temp/portable-build-'+[guid]::NewGuid().ToString('N'))
$package=Join-Path $stage 'Image Studio'
foreach($folder in 'app','desktop','portable/tools','runtime/custom_nodes/moss-image','licenses'){
    New-Item -ItemType Directory -Path (Join-Path $package $folder) -Force | Out-Null
}
dotnet publish (Join-Path $studioRoot 'desktop/ImageStudio.csproj') -c Release -r win-x64 --self-contained true -p:DebugType=None -p:DebugSymbols=false -p:RestoreSources=https://api.nuget.org/v3/index.json -p:NuGetAudit=false ('-p:RestorePackagesPath='+(Join-Path $studioRoot 'temp/portable-nuget')) -o (Join-Path $package 'app')
if($LASTEXITCODE -ne 0){throw 'Portable app build failed.'}
foreach($name in 'launch.py','Start Image Studio.ps1','Stop Image Studio.ps1','Stop Image Studio.cmd','Open ComfyUI.cmd'){
    Copy-Item -LiteralPath (Join-Path $studioRoot $name) -Destination $package
}
foreach($name in 'Setup.cmd','Start Image Studio.cmd','START HERE.html','extra_model_paths.yaml'){
    Copy-Item -LiteralPath (Join-Path $studioRoot "portable/$name") -Destination $package
}
foreach($name in 'Common.ps1','Install.ps1','Setup.ps1','catalog.json','MediaCommon.ps1','InstallMedia.ps1','media-runtime.json'){
    Copy-Item -LiteralPath (Join-Path $studioRoot "portable/$name") -Destination (Join-Path $package 'portable')
}
foreach($name in 'rewrite_prompt.py','prompt_profiles.py'){ Copy-Item -LiteralPath (Join-Path $studioRoot ('desktop/'+$name)) -Destination (Join-Path $package 'desktop') }
& (Join-Path $studioRoot 'Package Production.ps1') -Destination $package -SelfContained
# Qwen helper code is an explicitly selected, checksum-pinned optional download; never bundle it in the core.
Get-ChildItem -LiteralPath (Join-Path $studioRoot 'runtime/custom_nodes/moss-image') -File | Where-Object { $_.Extension -in '.py','.toml' -or $_.Name -eq 'LICENSE' } | Copy-Item -Destination (Join-Path $package 'runtime/custom_nodes/moss-image')
Copy-Item -LiteralPath (Join-Path $studioRoot 'LICENSE'),(Join-Path $studioRoot 'NOTICE') -Destination $package
$sevenPins=@{'7z.exe'='2bff20bd679d45166b8c2d039044a4ca16189e6d69ff9c82345b4c1306986ec4';'7z.dll'='9657871fdd714c96a3a21f59abf04abb14944516c2a10c8cb606c12a71a75957';'7z.sfx'='b6f342fe8a568cc14467d8fe12e266e63aaf805ecba430a51fd1af65b52c6df7'}
foreach($name in $sevenPins.Keys){
    if((Get-FileHash -LiteralPath (Join-Path $env:ProgramFiles "7-Zip/$name")).Hash.ToLower() -ne $sevenPins[$name]){throw "7-Zip differs from reviewed 26.01: $name"}
}
$sourceArchive=Join-Path $studioRoot 'portable/licenses/7z2601-src.7z'
if((Get-FileHash -LiteralPath $sourceArchive).Hash.ToLower() -ne '3cd6ec747db311ebd97a6e581827f69fc38e7cea2cea8b34999d455ab30ec32b'){throw '7-Zip source archive changed.'}
Copy-Item -LiteralPath $sourceArchive,(Join-Path $studioRoot 'portable/licenses/LGPL-2.1.txt') -Destination (Join-Path $package 'licenses')
foreach($name in '7z.exe','7z.dll'){
    Copy-Item -LiteralPath (Join-Path $env:ProgramFiles "7-Zip/$name") -Destination (Join-Path $package 'portable/tools')
}
Copy-Item -LiteralPath (Join-Path $env:ProgramFiles '7-Zip/License.txt') -Destination (Join-Path $package 'licenses/7-Zip.txt')
Copy-Item -LiteralPath (Join-Path $studioRoot 'portable/licenses/Qwen-Image-2.1.txt') -Destination (Join-Path $package 'licenses')
$runtime=Get-ChildItem -LiteralPath (Join-Path $studioRoot 'temp/portable-nuget/microsoft.netcore.app.runtime.win-x64') -Directory | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1
Copy-Item -LiteralPath (Join-Path $runtime.FullName 'LICENSE.TXT') -Destination (Join-Path $package 'licenses/Microsoft.NET.txt')
Copy-Item -LiteralPath (Join-Path $runtime.FullName 'THIRD-PARTY-NOTICES.TXT') -Destination (Join-Path $package 'licenses/Microsoft.NET-third-party.txt')
$desktopRuntime=Get-ChildItem -LiteralPath (Join-Path $studioRoot 'temp/portable-nuget/microsoft.windowsdesktop.app.runtime.win-x64') -Directory | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1
Copy-Item -LiteralPath (Join-Path $desktopRuntime.FullName 'LICENSE') -Destination (Join-Path $package 'licenses/Microsoft.WindowsDesktop.txt')
@{version='2.4.0-beta.1';engine='ComfyUI 0.42.1';portable=$true} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $package 'portable.json')
Copy-Item -LiteralPath (Join-Path $studioRoot 'portable/RELEASE VALIDATION.txt') -Destination $package
Copy-Item -LiteralPath (Join-Path $studioRoot 'portable/PROMPT REFINEMENT.txt') -Destination $package
@'
FoxWorx MotionLab portable 2.4.0-beta.1

Included third-party components:
- Microsoft .NET 10 Windows Desktop runtime: notices in this folder.
- 7-Zip: LGPL/BSD/unRAR terms in 7-Zip.txt. Source: https://www.7-zip.org/download.html
- MOSS-Image plugin: Apache 2.0 notice in runtime/custom_nodes/moss-image/LICENSE.
  Source revision 95559c93ce9f85967de70435deefc1153a1a2fab: https://github.com/OpenMOSS/MOSS-Image
- No Qwen prompt-rewrite implementation or model weights are included in this core package.

Downloaded separately after review and selection:
- Qwen3.5 4B/9B independent optional prompt refinement: original weights Apache-2.0; see portable/catalog.json.
  The retired Qwen Image 2.1 PE implementation and prompts are not used.
- Official ComfyUI portable 0.42.1: https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.42.1
  Its source and license files are included in the official portable download.
- llama.cpp b11146: https://github.com/ggml-org/llama.cpp/releases/tag/b11146
- Model repositories and license links: START HERE.html and portable/catalog.json.
Models retain their publishers' license terms; inclusion in this installer does not change them.
'@ | Set-Content -LiteralPath (Join-Path $package 'licenses/ABOUT.txt')
# Windows PowerShell 5.1 needs a BOM to read non-ASCII UI labels reliably.
Get-ChildItem -LiteralPath $package -Recurse -Filter *.ps1 | ForEach-Object {
    [IO.File]::WriteAllText($_.FullName,[IO.File]::ReadAllText($_.FullName),[Text.UTF8Encoding]::new($true))
}
$files=Get-ChildItem -LiteralPath $package -Recurse -File | Sort-Object FullName
$manifest=@($files | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()+'  '+[IO.Path]::GetRelativePath($package,$_.FullName).Replace('\','/') })
[IO.File]::WriteAllLines((Join-Path $package 'SHA256SUMS.txt'),$manifest,[Text.UTF8Encoding]::new($false))
Write-Output "PACKAGE=$package"
if($NoArchive){exit 0}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$archive=Join-Path $OutputDirectory 'FoxWorx-MotionLab-2.4.0-beta.1-Windows-Portable.exe'
$zip=Join-Path $OutputDirectory 'FoxWorx-MotionLab-2.4.0-beta.1-Windows-Portable.zip'
if((Test-Path -LiteralPath $archive) -or (Test-Path -LiteralPath $zip)){throw 'Output files already exist. Choose a new OutputDirectory to preserve the previous release.'}
$seven=Join-Path $env:ProgramFiles '7-Zip/7z.exe'
Push-Location $stage
try {
    & $seven a -t7z ('-sfx'+(Join-Path $env:ProgramFiles '7-Zip/7z.sfx')) $archive 'Image Studio' -mx=5 -bso0 -bsp0
    if($LASTEXITCODE -ne 0){throw 'Self-extracting installer creation failed.'}
    & $seven a -tzip $zip 'Image Studio' -mx=5 -bso0 -bsp0
    if($LASTEXITCODE -ne 0){throw 'Portable ZIP creation failed.'}
} finally {Pop-Location}
foreach($path in $archive,$zip){
    & $seven t $path -bso0 -bsp0
    if($LASTEXITCODE -ne 0){throw "Archive integrity check failed: $path"}
    ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()+'  '+[IO.Path]::GetFileName($path)) | Set-Content -LiteralPath ($path+'.sha256.txt')
    Write-Output "VERIFIED=$path"
}
