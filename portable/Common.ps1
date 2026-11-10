$ErrorActionPreference = 'Stop'
# A child Windows PowerShell process can inherit PowerShell 7's incompatible module path.
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1') -Force

# Hardware snapshots are local only. Never add GPUs together or infer CUDA support
# from Windows' shared graphics memory. The engine uses device zero, not the largest GPU.
function Convert-StudioGpuRows($Rows) {
    @($Rows | ForEach-Object {
        $parts = $_ -split ',\s*'
        if ($parts.Count -eq 5) {
            $total=0.0; $free=0.0
            if ([double]::TryParse($parts[2], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$total) -and
                [double]::TryParse($parts[3], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$free)) {
                [pscustomobject]@{Index=$parts[0];Name=$parts[1];VramGB=$total/1024;FreeVramGB=$free/1024;Driver=$parts[4]}
            }
        }
    })
}

function Get-StudioHardware {
    $ram=0.0; $freeRam=0.0; $cpu='Unknown'; $gpu=$null; $gpus=@(); $warnings=@()
    try {
        $ram=(Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory / 1GB
        $freeRam=(Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).FreePhysicalMemory / 1MB
        $cpu=(Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1).Name
    } catch { $warnings+='System memory detection failed; do not assume compatibility.' }
    $smi=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($smi) {
        $rows=& $smi.Source --query-gpu=index,name,memory.total,memory.free,driver_version --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0) { $gpus=@(Convert-StudioGpuRows $rows); $gpu=$gpus | Where-Object Index -eq '0' | Select-Object -First 1 }
    }
    if($gpus.Count -gt 1){$warnings+='Multiple GPUs detected: this setup checks GPU 0 only; VRAM is not combined.'}
    if($env:CUDA_VISIBLE_DEVICES){$warnings+='CUDA_VISIBLE_DEVICES overrides GPU selection; clear it or use a separately validated setup.'; $gpu=$null}
    [pscustomobject]@{RamGB=$ram;FreeRamGB=$freeRam;Cpu=$cpu;GpuName=$(if($gpu){$gpu.Name}else{'NVIDIA/CUDA compatibility unknown'});VramGB=$(if($gpu){$gpu.VramGB}else{0});FreeVramGB=$(if($gpu){$gpu.FreeVramGB}else{0});Driver=$(if($gpu){$gpu.Driver}else{'0.0'});X64=[Environment]::Is64BitOperatingSystem;Gpus=$gpus;Warnings=$warnings}
}

function Get-StudioCompatibility($Bundle, $Hardware) {
    if (-not $Hardware.X64) { return 'Requires 64-bit Windows.' }
    if ($Hardware.VramGB -le 0) { return 'An NVIDIA GPU and working driver detection are required; AMD/Intel/CPU inference is not validated.' }
    try { $driver=[version]$Hardware.Driver } catch { return 'NVIDIA driver version is unknown; refresh detection before downloading.' }
    if ($driver -lt [version]'580.88') { return 'Update the NVIDIA driver to 580.88 or newer for this CUDA 13 engine.' }
    # Allow only small firmware-reserved differences from nominal memory capacity.
    if (($Hardware.RamGB + 0.5) -lt $Bundle.minRamGB) { return "Needs $($Bundle.minRamGB) GB nominal system RAM; detected $([math]::Round($Hardware.RamGB,1)) GiB." }
    if (($Hardware.VramGB + 0.1) -lt $Bundle.minVramGB) { return "Setup floor: $($Bundle.minVramGB) GB nominal VRAM; detected $([math]::Round($Hardware.VramGB,1)) GiB. Smaller cards are not validated." }
    if ($Bundle.minFreeVramGB -and $Hardware.PSObject.Properties['FreeVramGB'] -and $Hardware.FreeVramGB -lt $Bundle.minFreeVramGB) { return "Close other GPU applications: this option needs $($Bundle.minFreeVramGB) GiB free VRAM." }
    return ''
}

function Test-StudioConsent($Consent, [string[]]$Selected, [string]$CatalogPath) {
    if(-not $Consent -or $Consent.acknowledged -ne $true -or $Consent.catalogSha256 -ne (Get-FileHash -LiteralPath $CatalogPath -Algorithm SHA256).Hash){throw 'Review the current model licenses and download plan in Setup before installing.'}
    if((@($Consent.selected | Sort-Object -Unique) -join ',') -ne (@($Selected | Sort-Object -Unique) -join ',')){throw 'Model selection changed after approval. Review the download plan again.'}
}

function Get-StudioPath([string]$Root, [string]$Relative) {
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $path.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid package path: $Relative" }
    return $path
}

function Get-StudioPlan($Catalog, [string[]]$Selected, $Hardware) {
    if(-not $Selected -or $Selected.Count -eq 0){return @()}
    foreach ($id in $Selected) {
        $bundle = $Catalog.bundles | Where-Object id -eq $id
        if (-not $bundle) { throw "Unknown download choice: $id" }
        $reason = Get-StudioCompatibility $bundle $Hardware
        if ($reason) { throw "$($bundle.title): $reason" }
    }
    $all=@($Catalog.engine) + @($Catalog.bundles | Where-Object { $_.id -in $Selected } | ForEach-Object { $_.files })
    foreach($group in $all | Group-Object path){
        if(@($group.Group.sha256 | Select-Object -Unique).Count -ne 1){throw 'Conflicting checksums for a shared download.'}
        $group.Group[0]
    }
}

function Save-StudioDownload($Entry, [string]$Root) {
    $path = Get-StudioPath $Root $Entry.path
    $uri = [uri]$Entry.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin 'github.com','huggingface.co','raw.githubusercontent.com','docs.nvidia.com') { throw "Untrusted download source: $($uri.Host)" }
    if ($Entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $Entry.bytes -le 0) { throw "Incomplete checksum metadata for $($Entry.path)" }
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -eq $Entry.bytes) {
        Write-Output "Checking $($Entry.path)..."
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $Entry.sha256) { Write-Output "Verified $($Entry.path)"; return }
    }
    New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
    $partial = $path + '.partial'
    Write-Output "Downloading $($Entry.path) ($([math]::Round($Entry.bytes/1GB,2)) GiB)..."
    if (-not (Test-Path -LiteralPath $partial) -or (Get-Item -LiteralPath $partial).Length -lt $Entry.bytes) {
        & curl.exe --fail --location --retry 5 --retry-delay 2 --connect-timeout 30 --speed-limit 1024 --speed-time 120 --continue-at - --output $partial $Entry.url
        if ($LASTEXITCODE -ne 0) { throw "Download paused for $($Entry.path). Run Setup again to resume. curl exit code: $LASTEXITCODE" }
    }
    if ((Get-Item -LiteralPath $partial).Length -ne $Entry.bytes -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Entry.sha256) {
        Remove-Item -LiteralPath $partial
        throw "Checksum mismatch for $($Entry.path). The incomplete file was discarded; run Setup again."
    }
    Move-Item -LiteralPath $partial -Destination $path -Force
    Write-Output "Verified $($Entry.path)"
}
