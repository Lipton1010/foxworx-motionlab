$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_CLI_HOME = Join-Path $PSScriptRoot 'temp/dotnet'
dotnet publish (Join-Path $PSScriptRoot 'desktop/ImageStudio.csproj') -c Release -o (Join-Path $PSScriptRoot 'app') --self-contained false
if ($LASTEXITCODE -ne 0) { throw 'Image Studio could not be built.' }
