param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'app'))
$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_CLI_HOME = Join-Path $PSScriptRoot 'temp/dotnet'
dotnet publish (Join-Path $PSScriptRoot 'desktop/ImageStudio.csproj') -c Release --artifacts-path (Join-Path $PSScriptRoot 'temp/film-package-artifacts') -o $OutputDirectory --self-contained false -p:NuGetAudit=false -p:RestoreIgnoreFailedSources=true
if ($LASTEXITCODE -ne 0) { throw 'Image Studio could not be built.' }
$desktopPackageRoot=Split-Path -Parent ([IO.Path]::GetFullPath($OutputDirectory))
if($desktopPackageRoot -ne [IO.Path]::GetFullPath($PSScriptRoot)){
    foreach($name in 'launch.py','Start Image Studio.ps1','Stop Image Studio.ps1','extra_model_paths.yaml'){
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $desktopPackageRoot
    }
}
& (Join-Path $PSScriptRoot 'Package Production.ps1') -Destination $desktopPackageRoot
