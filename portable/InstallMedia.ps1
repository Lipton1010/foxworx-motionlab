param([string]$ConsentFile, [switch]$PlanOnly)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
. (Join-Path $PSScriptRoot 'MediaCommon.ps1')
$root=Split-Path $PSScriptRoot
$manifestPath=Join-Path $PSScriptRoot 'media-runtime.json'
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if($PlanOnly){$manifest | ConvertTo-Json -Depth 6;exit 0}
if(-not $ConsentFile){throw 'Open Setup > Media tools to review and approve the upstream download.'}
$consent=Get-Content -LiteralPath $ConsentFile -Raw | ConvertFrom-Json
Test-StudioMediaConsent $consent $manifestPath
$verified=0
foreach($file in $manifest.files){
    $target=Get-StudioPath $root ('runtime/media/'+$file.name)
    if(Test-Path -LiteralPath $target){
        if((Get-Item -LiteralPath $target).Length -ne $file.bytes -or (Get-FileHash -LiteralPath $target).Hash -ne $file.sha256){throw 'Existing media tools were preserved. Configure your existing tools, or move them yourself before installing this version.'}
        $verified++
    }
}
if($verified -eq $manifest.files.Count){Write-Output 'The selected media tools and GPL notice are already verified. No download or change needed.';exit 0}
$drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($root))
if($drive.AvailableFreeSpace -lt ($manifest.bytes+($manifest.files | Measure-Object bytes -Sum).Sum+1GB)){throw 'Keep at least 2 GiB free for media tools and download staging.'}
Save-StudioDownload $manifest $root
Install-StudioMediaArchive $manifest $root (Get-StudioPath $root $manifest.path)
