param([Parameter(Mandatory=$true)][string]$SelectionFile, [string]$ConsentFile, [switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$studioRoot = Split-Path $PSScriptRoot
try {
    $catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    [string[]]$selected = Get-Content -LiteralPath $SelectionFile -Raw | ConvertFrom-Json
    $hardware = Get-StudioHardware
    $engineRequirement = [pscustomobject]@{minRamGB=16;minVramGB=8}
    $reason = Get-StudioCompatibility $engineRequirement $hardware
    if ($selected.Count -gt 0 -and $reason) { throw $reason }
    $plan = @(Get-StudioPlan $catalog $selected $hardware)
    if ($PlanOnly) { @{hardware=$hardware;downloads=$plan;bytes=($plan | Measure-Object bytes -Sum).Sum} | ConvertTo-Json -Depth 10; exit 0 }
    if(-not $ConsentFile){throw 'Explicit download and license review is required. Use Setup.'}
    $consent=Get-Content -LiteralPath $ConsentFile -Raw | ConvertFrom-Json
    Test-StudioConsent $consent $selected (Join-Path $PSScriptRoot 'catalog.json')
    if(-not $selected -or $selected.Count -eq 0){
        Write-Output 'Core-only harness is ready. No models or engine were downloaded. Generation remains unavailable until you add a supported pack.'
        exit 0
    }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($studioRoot))
    $missingBytes = ($plan | Where-Object { $p=Get-StudioPath $studioRoot $_.path; -not (Test-Path -LiteralPath $p) -or (Get-Item -LiteralPath $p).Length -ne $_.bytes } | Measure-Object bytes -Sum).Sum
    if ($drive.AvailableFreeSpace -lt ($missingBytes + 20GB)) { throw "Not enough free disk space. Keep at least $([math]::Ceiling(($missingBytes+20GB)/1GB)) GiB free for these downloads and engine extraction." }
    foreach ($folder in 'user','input','output','temp','logs','models/loras','runtime') { New-Item -ItemType Directory -Path (Join-Path $studioRoot $folder) -Force | Out-Null }
    Save-StudioDownload $catalog.engine $studioRoot
    $engineRoot = Join-Path $studioRoot 'runtime/ComfyUI_windows_portable'
    $engineMarker = Join-Path $engineRoot 'image-studio-engine.sha256'
    if (-not (Test-Path -LiteralPath $engineMarker) -or (Get-Content -LiteralPath $engineMarker -Raw).Trim() -ne $catalog.engine.sha256) {
        Write-Output 'Extracting the private engine. This can take several minutes...'
        & (Join-Path $PSScriptRoot 'tools/7z.exe') x (Get-StudioPath $studioRoot $catalog.engine.path) ('-o'+(Join-Path $studioRoot 'runtime')) -y -bso0 -bsp0
        if ($LASTEXITCODE -ne 0) { throw 'Engine extraction failed. Run Setup again to repair it.' }
        Set-Content -LiteralPath $engineMarker -Value $catalog.engine.sha256
    }
    $python = Join-Path $engineRoot 'python_embeded/python.exe'
    Write-Output 'Checking the engine, NVIDIA driver, and GPU...'
    & $python -s -c "import torch; assert torch.cuda.is_available(), 'CUDA is unavailable; update the NVIDIA driver'; print('Engine GPU:', torch.cuda.get_device_name(0)); print('VRAM GiB:', round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)); print('CUDA runtime:', torch.version.cuda)"
    if ($LASTEXITCODE -ne 0) { throw 'The GPU check failed. Update the NVIDIA driver, then run Setup again. If Windows reports VCRUNTIME or c10.dll missing, install Microsoft Visual C++ x64 runtime from https://aka.ms/vc14/vc_redist.x64.exe.' }
    foreach ($bundle in $catalog.bundles | Where-Object { $_.id -in $selected }) {
        Write-Output "Installing $($bundle.title)..."
        foreach ($entry in $bundle.files) {
            Save-StudioDownload $entry $studioRoot
            if ($entry.extractTo) {
                $destination = Get-StudioPath $studioRoot $entry.extractTo
                New-Item -ItemType Directory -Path $destination -Force | Out-Null
                & (Join-Path $PSScriptRoot 'tools/7z.exe') e (Get-StudioPath $studioRoot $entry.path) ('-o'+$destination) -y -bso0 -bsp0
                if ($LASTEXITCODE -ne 0) { throw "Could not extract $($entry.path). Run Setup again." }
            }
        }
        if ($bundle.refinerTier) {
            $model=$bundle.files | Where-Object role -eq 'model'
            $projector=$bundle.files | Where-Object role -eq 'projector'
            $runtimePath=Join-Path $studioRoot 'runtime/llama-qwen35/llama-server.exe'
            if(-not (Test-Path -LiteralPath $runtimePath)){throw 'Verified runtime archive did not contain llama-server.exe.'}
            $receipt=@{family='qwen3.5';tier=$bundle.refinerTier;license='Apache-2.0';revision=$bundle.modelRevision;
                model=@{path=$model.path;sha256=$model.sha256};projector=@{path=$projector.path;sha256=$projector.sha256};
                runtime=@{path='runtime/llama-qwen35/llama-server.exe';sha256=(Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash.ToLower()};
                validation=$bundle.validation}
            $receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $studioRoot ('models/prompt-refiner/'+$bundle.refinerTier+'.json'))
        }
        if ($bundle.id -eq 'moss') { $bundle | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $studioRoot 'models/moss-image-base/install-manifest.json') }
    }
    @{ version=$catalog.version; installed=(Get-Date).ToString('o'); selected=$selected; hardware=$hardware; licenseReview=$consent } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $studioRoot 'user/setup-receipt.json')
    Write-Output 'Setup complete. Open Image Studio. Start with 1 megapixel images or a 3-second video.'
    exit 0
} catch {
    Write-Output ('SETUP FAILED: ' + $_.Exception.Message)
    exit 1
}
