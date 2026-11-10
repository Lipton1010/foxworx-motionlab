$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
. (Join-Path $root 'portable/Common.ps1')
. (Join-Path $root 'portable/MediaCommon.ps1')
$count=0
function Check($value,$label){if(-not $value){throw "FAIL: $label"};$script:count++;Write-Output "PASS: $label"}
$temp=Join-Path $root ('Output/media-tests-'+[guid]::NewGuid().ToString('N'))
$source=Join-Path $temp 'source';New-Item -ItemType Directory $source -Force|Out-Null
$files=@()
foreach($name in 'ffmpeg.exe','ffprobe.exe','LICENSE.txt'){
 $path=Join-Path $source $name;[IO.File]::WriteAllText($path,('synthetic '+$name))
 $files+=@{name=$name;entry=$name;bytes=(Get-Item $path).Length;sha256=(Get-FileHash $path).Hash.ToLower()}
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=Join-Path $temp 'fixture.zip';[IO.Compression.ZipFile]::CreateFromDirectory($source,$archive)
$manifest=[pscustomobject]@{publisher='Synthetic fixture';releaseUrl='https://example.invalid';license='fixture';files=$files;bytes=(Get-Item $archive).Length;sha256=(Get-FileHash $archive).Hash.ToLower()}
$manifestPath=Join-Path $temp 'manifest.json';$manifest|ConvertTo-Json -Depth 5|Set-Content $manifestPath
try{Test-StudioMediaConsent ([pscustomobject]@{acknowledged=$false;manifestSha256='bad'}) $manifestPath;throw 'accepted'}catch{Check ($_.Exception.Message -match 'explicit approval') 'No unapproved download consent'}
Test-StudioMediaConsent ([pscustomobject]@{acknowledged=$true;manifestSha256=(Get-FileHash $manifestPath).Hash}) $manifestPath
Check $true 'Consent binds exact manifest'
try{Test-StudioMediaConsent ([pscustomobject]@{acknowledged='true';manifestSha256=(Get-FileHash $manifestPath).Hash}) $manifestPath;throw 'accepted'}catch{Check ($_.Exception.Message -match 'explicit approval') 'String truthiness cannot authorize a download'}
$install=Join-Path $temp 'install';New-Item -ItemType Directory $install|Out-Null
Install-StudioMediaArchive $manifest $install $archive
foreach($file in $files){Check ((Get-FileHash (Join-Path $install ('runtime/media/'+$file.name))).Hash -eq $file.sha256) ('Verified installed '+$file.name)}
Install-StudioMediaArchive $manifest $install $archive
Check $true 'Verified installation is safely resumable'
$legacy=Join-Path $temp 'legacy';New-Item -ItemType Directory (Join-Path $legacy 'runtime/media') -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $legacy 'runtime/media/ffmpeg.exe'),'keep existing')
try{Install-StudioMediaArchive $manifest $legacy $archive;throw 'overwritten'}catch{Check ($_.Exception.Message -match 'preserved') 'Different existing media tool cannot be replaced'}
Check ((Get-Content (Join-Path $legacy 'runtime/media/ffmpeg.exe') -Raw) -eq 'keep existing') 'Existing bytes unchanged'
$manifest.sha256='0'*64
try{Install-StudioMediaArchive $manifest $install $archive;throw 'accepted'}catch{Check ($_.Exception.Message -match 'checksum mismatch') 'Wrong archive digest is rejected'}
$production=Get-Content (Join-Path $root 'Package Production.ps1') -Raw
Check (-not $production.Contains('chocolatey')) 'Packaging cannot copy Chocolatey media binaries/notices'
$real=Get-Content (Join-Path $root 'portable/media-runtime.json') -Raw|ConvertFrom-Json
Check ($real.url -match '/autobuild-2026-11-09-12-42/' -and $real.sha256 -match '^[a-f0-9]{64}$') 'Media source is dated and checksum pinned'
Check ($real.files.Count -eq 3) 'Only required executables and GPL text are installed'
Write-Output "$count media setup checks passed. No network requests or executable launch."
