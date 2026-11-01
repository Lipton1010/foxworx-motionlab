$ErrorActionPreference = 'Stop'
$studioExecutable = Join-Path $PSScriptRoot 'app\Image Studio.exe'
if (-not (Test-Path -LiteralPath $studioExecutable)) { throw 'Build Image Studio before creating its shortcut.' }
$studioShell = New-Object -ComObject WScript.Shell
$studioDesktop = [Environment]::GetFolderPath('Desktop')
foreach ($studioShortcutPath in @((Join-Path $PSScriptRoot 'Image Studio.lnk'), (Join-Path $studioDesktop 'Image Studio.lnk'))) {
    $studioShortcut = $studioShell.CreateShortcut($studioShortcutPath)
    if ((Test-Path -LiteralPath $studioShortcutPath) -and $studioShortcut.TargetPath -ne $studioExecutable) {
        throw "A shortcut to a different app already exists at $studioShortcutPath. It was not replaced."
    }
    $studioShortcut.TargetPath = $studioExecutable
    $studioShortcut.WorkingDirectory = $PSScriptRoot
    $studioShortcut.IconLocation = "$studioExecutable,0"
    $studioShortcut.Description = 'Create and edit images locally'
    $studioShortcut.Save()
    Write-Output "Created: $studioShortcutPath"
}
