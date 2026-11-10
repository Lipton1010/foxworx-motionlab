function Test-StudioMediaConsent($Consent, [string]$ManifestPath) {
    if($Consent.acknowledged -isnot [bool] -or $Consent.acknowledged -ne $true -or $Consent.manifestSha256 -ne (Get-FileHash -LiteralPath $ManifestPath).Hash){
        throw 'Media download requires explicit approval of this exact publisher, license and manifest. Open Setup > Media tools.'
    }
}

function Install-StudioMediaArchive($Manifest, [string]$Root, [string]$Archive) {
    # Refuse redirected destination components rather than following a junction
    # outside the installation selected by the user.
    $base=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $probe=Get-StudioPath $Root 'runtime/media'
    while($probe.Length -ge $base.Length){
        if((Test-Path -LiteralPath $probe) -and ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){
            throw 'Media destination contains a redirected path; no files were installed.'
        }
        if($probe -eq $base){break}
        $probe=Split-Path -Parent $probe
    }
    if((Get-Item -LiteralPath $Archive).Length -ne $Manifest.bytes -or (Get-FileHash -LiteralPath $Archive).Hash -ne $Manifest.sha256){throw 'Media archive checksum mismatch.'}
    $names=@($Manifest.files | ForEach-Object name)
    if($names.Count -ne 3 -or 'ffmpeg.exe' -notin $names -or 'ffprobe.exe' -notin $names -or 'LICENSE.txt' -notin $names){throw 'Invalid media file manifest.'}
    foreach($file in $Manifest.files){
        if($file.name -notmatch '^[a-zA-Z0-9_.-]+$' -or $file.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $file.bytes -le 0){throw 'Invalid media file metadata.'}
        $target=Get-StudioPath $Root ('runtime/media/'+$file.name)
        if((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Media file is a redirected path; existing files were preserved.'}
        if((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target).Length -ne $file.bytes -or (Get-FileHash -LiteralPath $target).Hash -ne $file.sha256)){
            throw 'Existing media tools were preserved. Use your configured tools, or move them yourself before installing this version. No files were replaced.'
        }
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        # Validate the complete closure before creating any executable.
        foreach($file in $Manifest.files){
            $entry=$zip.GetEntry($file.entry)
            if(-not $entry -or $entry.Length -ne $file.bytes){throw ('Missing or invalid media entry: '+$file.name)}
            $stream=$entry.Open(); $sha=[Security.Cryptography.SHA256]::Create()
            try {$digest=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLower()}
            finally {$stream.Dispose();$sha.Dispose()}
            if($digest -ne $file.sha256){throw ('Media entry checksum mismatch: '+$file.name)}
        }
        $destination=Get-StudioPath $Root 'runtime/media'
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        foreach($file in $Manifest.files){
            $target=Get-StudioPath $Root ('runtime/media/'+$file.name)
            if(Test-Path -LiteralPath $target){continue} # Already verified; resumable, never overwrite.
            $temporary=$target+'.'+[guid]::NewGuid().ToString('N')+'.incoming'
            $sourceStream=$zip.GetEntry($file.entry).Open();$output=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew)
            try {$sourceStream.CopyTo($output)} finally {$sourceStream.Dispose();$output.Dispose()}
            Move-Item -LiteralPath $temporary -Destination $target # No Force: preserve racing/user files.
        }
        $record=Get-StudioPath $Root 'runtime/media/upstream-install.json'
        $temporary=$record+'.tmp'
        @{publisher=$Manifest.publisher;release=$Manifest.releaseUrl;archiveSha256=$Manifest.sha256;license=$Manifest.license;files=$Manifest.files;installedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary
        Move-Item -LiteralPath $temporary -Destination $record -Force
    } finally {$zip.Dispose()}
    Write-Output 'Media tools installed from the reviewed upstream archive. The GPL notice is in runtime/media/LICENSE.txt. No media or prompts were uploaded.'
}
