$ErrorActionPreference = 'Stop'
# A child Windows PowerShell process can inherit PowerShell 7's incompatible module path.
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1') -Force

function Get-StudioHardware {
    $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $gpu = $null
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($smi) {
        $rows = & $smi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0) {
            $gpu = @($rows | ForEach-Object {
                $parts = $_ -split ',\s*'
                if ($parts.Count -eq 3) { [pscustomobject]@{ Name=$parts[0]; VramGB=[math]::Round([double]$parts[1]/1024); Driver=$parts[2] } }
            } | Sort-Object VramGB -Descending)[0]
        }
    }
    [pscustomobject]@{ RamGB=$ram; GpuName=$(if ($gpu) {$gpu.Name} else {'No NVIDIA GPU detected'}); VramGB=$(if ($gpu) {$gpu.VramGB} else {0}); Driver=$(if ($gpu) {$gpu.Driver} else {'0.0'}); X64=[Environment]::Is64BitOperatingSystem }
}

function Get-StudioCompatibility($Bundle, $Hardware) {
    if (-not $Hardware.X64) { return 'Requires 64-bit Windows.' }
    if ($Hardware.VramGB -eq 0) { return 'An NVIDIA RTX GPU and its driver are required.' }
    if ([version]$Hardware.Driver -lt [version]'580.88') { return 'Update the NVIDIA driver to 580.88 or newer for this CUDA 13 engine.' }
    if ($Hardware.RamGB -lt $Bundle.minRamGB) { return "Needs at least $($Bundle.minRamGB) GB system RAM; this PC has $($Hardware.RamGB) GB." }
    if ($Hardware.VramGB -lt $Bundle.minVramGB) { return "Needs at least $($Bundle.minVramGB) GB VRAM; this GPU has $($Hardware.VramGB) GB." }
    return ''
}

function Get-StudioPath([string]$Root, [string]$Relative) {
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $path.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid package path: $Relative" }
    return $path
}

function Get-StudioPlan($Catalog, [string[]]$Selected, $Hardware) {
    foreach ($id in $Selected) {
        $bundle = $Catalog.bundles | Where-Object id -eq $id
        if (-not $bundle) { throw "Unknown download choice: $id" }
        $reason = Get-StudioCompatibility $bundle $Hardware
        if ($reason) { throw "$($bundle.title): $reason" }
    }
    @($Catalog.engine) + @($Catalog.bundles | Where-Object { $_.id -in $Selected } | ForEach-Object { $_.files })
}

function Save-StudioDownload($Entry, [string]$Root) {
    $path = Get-StudioPath $Root $Entry.path
    $uri = [uri]$Entry.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin 'github.com','huggingface.co','raw.githubusercontent.com') { throw "Untrusted download source: $($uri.Host)" }
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
