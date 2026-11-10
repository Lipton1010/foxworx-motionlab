param([switch]$SmokeTest, [string]$ScreenshotPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$studioRoot = Split-Path $PSScriptRoot
$catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$hardware = Get-StudioHardware
$script:worker = $null
$form = New-Object Windows.Forms.Form
$form.Text = 'FoxWorx MotionLab - Beta Setup'
$form.Size = New-Object Drawing.Size(920,920)
$form.MinimumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI',10)
$form.BackColor = [Drawing.Color]::White
$layout = New-Object Windows.Forms.TableLayoutPanel
$layout.Dock = 'Fill'; $layout.AutoScroll=$true; $layout.Padding = New-Object Windows.Forms.Padding(22); $layout.ColumnCount=1; $layout.RowCount=7
foreach ($height in 54,100,370,46,38,115,50) { $layout.RowStyles.Add((New-Object Windows.Forms.RowStyle([Windows.Forms.SizeType]::Absolute,$height))) | Out-Null }
$form.Controls.Add($layout)
$heading = New-Object Windows.Forms.Label
$heading.Text='Choose what to download'; $heading.Font=New-Object Drawing.Font('Segoe UI',20,[Drawing.FontStyle]::Bold); $heading.Dock='Fill'
$layout.Controls.Add($heading,0,0)
$machine=New-Object Windows.Forms.Label
$drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($studioRoot))
$machine.Text="$($hardware.GpuName): $([math]::Round($hardware.VramGB,1)) GiB total / $([math]::Round($hardware.FreeVramGB,1)) GiB free VRAM; driver $($hardware.Driver)`nRAM: $([math]::Round($hardware.RamGB,1)) GiB total / $([math]::Round($hardware.FreeRamGB,1)) GiB free. Disk: $([math]::Round($drive.AvailableFreeSpace/1GB,1)) GiB free.`nCPU: $($hardware.Cpu). No automatic CPU inference fallback. Checks stay on this PC.`n$($hardware.Warnings -join ' ')"
$machine.Dock='Fill'; $layout.Controls.Add($machine,0,1)
$choices=New-Object Windows.Forms.FlowLayoutPanel
$choices.Dock='Fill'; $choices.FlowDirection='TopDown'; $choices.WrapContents=$false; $choices.AutoScroll=$true
$layout.Controls.Add($choices,0,2)
$checks=@()
$tips=New-Object Windows.Forms.ToolTip
foreach ($bundle in $catalog.bundles) {
    $check=New-Object Windows.Forms.CheckBox
    $check.AutoSize=$false; $check.Width=760; $check.Height=72; $check.Tag=$bundle.id
    $reason=Get-StudioCompatibility $bundle $hardware
    $check.Text="$($bundle.title) — $([math]::Round($bundle.bytes/1e9,1)) GB download`nSetup floor: $($bundle.minVramGB) GB VRAM / $($bundle.minRamGB) GB RAM (not a certified minimum)`n"+$(if($reason){$reason}else{$bundle.description})
    $check.Enabled=[string]::IsNullOrEmpty($reason); $check.Checked=$false
    $tips.SetToolTip($check,($bundle.validation+"`n"+$bundle.licenseSummary+"`nLicense: "+$bundle.licenseUrl))
    $choices.Controls.Add($check); $checks += $check
}
$total=New-Object Windows.Forms.Label; $total.Dock='Fill'; $layout.Controls.Add($total,0,3)
$refreshTotal={
    $ids=@($checks | Where-Object Checked | ForEach-Object Tag)
    $engineBytes=0; if($ids.Count -gt 0){$engineBytes=$catalog.engine.bytes}
    $bytes=(@(Get-StudioPlan $catalog $ids $hardware) | Measure-Object bytes -Sum).Sum
    if($ids.Count -eq 0){$total.Text="Core-only harness: no model or engine download. Open Image Studio for planning/imported media; add supported packs when ready."; return}
    $total.Text="Selected downloads: $([math]::Round($bytes/1e9,1)) GB, including the required 2 GB engine.`nKeep another 20 GiB free for extraction and working space. Existing verified downloads are reused."
}
foreach($check in $checks){$check.Add_CheckedChanged($refreshTotal)}
& $refreshTotal
$license=New-Object Windows.Forms.LinkLabel; $license.Text='Model licenses and hardware notes'; $license.AutoSize=$true
$license.Add_LinkClicked({Start-Process (Join-Path $studioRoot 'START HERE.html')})
$layout.Controls.Add($license,0,4)
$progress=New-Object Windows.Forms.TextBox; $progress.Multiline=$true; $progress.ReadOnly=$true; $progress.ScrollBars='Vertical'; $progress.Dock='Fill'; $progress.Text='Select the models you want. You can run Setup again later to add others.'
$layout.Controls.Add($progress,0,5)
$actions=New-Object Windows.Forms.FlowLayoutPanel; $actions.Dock='Fill'
$install=New-Object Windows.Forms.Button; $install.Text='Install selected'; $install.Width=145; $install.Height=36
$cancel=New-Object Windows.Forms.Button; $cancel.Text='Cancel download'; $cancel.Width=145; $cancel.Height=36; $cancel.Enabled=$false
$open=New-Object Windows.Forms.Button; $open.Text='Open Image Studio'; $open.Width=165; $open.Height=36
$open.Add_Click({Start-Process (Join-Path $studioRoot 'app/Image Studio.exe')})
$refresh=New-Object Windows.Forms.Button; $refresh.Text='Recheck hardware'; $refresh.Width=145; $refresh.Height=36
$media=New-Object Windows.Forms.Button; $media.Text='Media tools'; $media.Width=125; $media.Height=36
$media.Add_Click({
    if($script:worker -and -not $script:worker.HasExited){return}
    try {
        $manifestPath=Join-Path $PSScriptRoot 'media-runtime.json'
        $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $review=New-Object Windows.Forms.Form; $review.Text='Optional upstream media tools'; $review.Size=New-Object Drawing.Size(760,430); $review.StartPosition='CenterParent'
        $description=New-Object Windows.Forms.Label; $description.Dock='Fill';$description.Padding=New-Object Windows.Forms.Padding(18)
        $description.Text="$($manifest.title)`nPublisher: $($manifest.publisher)`nDownload: $([math]::Round($manifest.bytes/1MB)) MiB. Keep 2 GiB free. No GPU required.`n`nFFmpeg/FFprobe are not bundled with this app. They support media inspection, editing and export. This downloads directly from the publisher and verifies the archive and individual file checksums.`n`nLicense: $($manifest.license). Existing different tools are preserved. No media files or prompts are uploaded. This download does not grant model rights or settle every licensing obligation."
        $bottom=New-Object Windows.Forms.FlowLayoutPanel;$bottom.Dock='Bottom';$bottom.Height=95
        $link=New-Object Windows.Forms.LinkLabel;$link.Text='Read GPL license';$link.Width=200;$link.Height=30;$link.Tag=$manifest.licenseUrl
        $link.Add_LinkClicked({param($sender,$eventArgs) Start-Process $sender.Tag})
        $approve=New-Object Windows.Forms.Button;$approve.Text='Approve download';$approve.Width=160;$approve.DialogResult='OK'
        $back=New-Object Windows.Forms.Button;$back.Text='Cancel';$back.DialogResult='Cancel'
        $bottom.Controls.AddRange(@($link,$approve,$back));$review.Controls.Add($description);$review.Controls.Add($bottom);$review.CancelButton=$back
        $approved=$review.ShowDialog($form) -eq 'OK';$review.Dispose();if(-not $approved){return}
        foreach($folder in 'temp','logs'){New-Item -ItemType Directory -Path (Join-Path $studioRoot $folder) -Force | Out-Null}
        $consent=Join-Path $studioRoot 'temp/media-consent.json'
        @{acknowledged=$true;manifestSha256=(Get-FileHash -LiteralPath $manifestPath).Hash;reviewedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $consent
        $script:downloadEntries=@($manifest)
        $install.Enabled=$false;$choices.Enabled=$false;$refresh.Enabled=$false;$cancel.Enabled=$true;$open.Enabled=$false
        $script:worker=Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'InstallMedia.ps1')+'"'),'-ConsentFile',('"'+$consent+'"') -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError $errlog
        $null=$script:worker.Handle;$timer.Start()
    } catch {$progress.Text=$_.Exception.Message;$install.Enabled=$true;$choices.Enabled=$true;$refresh.Enabled=$true;$cancel.Enabled=$false;$open.Enabled=$true}
})
$refresh.Add_Click({
    $script:hardware=Get-StudioHardware
    $machine.Text="$($hardware.GpuName): $([math]::Round($hardware.VramGB,1)) GiB total / $([math]::Round($hardware.FreeVramGB,1)) GiB free VRAM; driver $($hardware.Driver)`nRAM: $([math]::Round($hardware.RamGB,1)) GiB total / $([math]::Round($hardware.FreeRamGB,1)) GiB free. Disk: $([math]::Round($drive.AvailableFreeSpace/1GB,1)) GiB free.`nCPU: $($hardware.Cpu). No automatic CPU inference fallback. Checks stay on this PC.`n$($hardware.Warnings -join ' ')"
    foreach($check in $checks){
        $bundle=$catalog.bundles | Where-Object id -eq $check.Tag
        $reason=Get-StudioCompatibility $bundle $hardware
        $check.Enabled=[string]::IsNullOrEmpty($reason)
        if(-not $check.Enabled){$check.Checked=$false}
        $check.Text="$($bundle.title) - $([math]::Round($bundle.bytes/1e9,1)) GB download`nSetup floor: $($bundle.minVramGB) GB VRAM / $($bundle.minRamGB) GB RAM (not a certified minimum)`n"+$(if($reason){$reason}else{$bundle.description})
    }
    & $refreshTotal
})
$actions.Controls.AddRange(@($install,$cancel,$open,$refresh,$media)); $layout.Controls.Add($actions,0,6)
$timer=New-Object Windows.Forms.Timer; $timer.Interval=500
$log=Join-Path $studioRoot 'logs/setup.log'; $errlog=Join-Path $studioRoot 'logs/setup-errors.log'
$timer.Add_Tick({
    if(Test-Path -LiteralPath $log){$progress.Text=(Get-Content -LiteralPath $log -Tail 9)-join "`r`n"; $progress.SelectionStart=$progress.Text.Length; $progress.ScrollToCaret()}
    foreach($entry in $script:downloadEntries){
        $partial=(Get-StudioPath $studioRoot $entry.path)+'.partial'
        if(Test-Path -LiteralPath $partial){
            $received=(Get-Item -LiteralPath $partial).Length
            $progress.AppendText("`r`nCurrent download: $([math]::Round(100*$received/$entry.bytes,1))% ($([math]::Round($received/1GB,2)) / $([math]::Round($entry.bytes/1GB,2)) GiB)")
            break
        }
    }
    if($script:worker -and $script:worker.HasExited){
        $timer.Stop(); $install.Enabled=$true; $choices.Enabled=$true; $refresh.Enabled=$true; $cancel.Enabled=$false; $open.Enabled=$true
        if($script:worker.ExitCode -ne 0){$progress.AppendText("`r`nSetup stopped. Fix the message above, then repeat the same setup action to resume. See logs/setup-errors.log for download details.")}
        $script:worker.Dispose(); $script:worker=$null
    }
})
$install.Add_Click({
    try {
        if($studioRoot.StartsWith('\\')){throw 'Extract the package to a local drive before installing.'}
        $hardware=Get-StudioHardware # Recheck immediately before approving downloads.
        $ids=@($checks | Where-Object Checked | ForEach-Object Tag)
        $reason=Get-StudioCompatibility ([pscustomobject]@{minRamGB=16;minVramGB=8}) $hardware
        if($ids.Count -gt 0 -and $reason){throw $reason}
        if($ids.Count -eq 0){$progress.Text="Core-only harness needs no model download or GPU. Use Open Image Studio; generation requires a supported pack."; return}
        $script:downloadEntries=@(Get-StudioPlan $catalog $ids $hardware)
        $review=New-Object Windows.Forms.Form
        $review.Text='Review downloads and model terms'; $review.Size=New-Object Drawing.Size(820,640); $review.StartPosition='CenterParent'
        $text=New-Object Windows.Forms.TextBox; $text.Multiline=$true; $text.ReadOnly=$true; $text.ScrollBars='Vertical'; $text.Dock='Fill'
        $lines=@('The app is a harness. Optional models and helper code retain their own licenses.', 'Hardware checks are estimates, not proof that every job will fit. No inference is run by this check.', 'Engine download: 2.02 GB. Reserve at least 20 GiB extra for extraction/workspace.', '')
        foreach($bundle in $catalog.bundles | Where-Object { $_.id -in $ids }){
            $lines+=@($bundle.title, "Download: $([math]::Round($bundle.bytes/1e9,2)) GB. VRAM setup floor: $($bundle.minVramGB) GB; RAM: $($bundle.minRamGB) GB.", $bundle.validation, $bundle.licenseSummary, $bundle.licenseUrl, ($bundle.additionalLicenseUrls -join "`r`n"), '')
        }
        $lines+='Read the linked publisher terms in Model licenses and hardware notes. Restricted or gated models require your own permission/account; the app does not grant rights or bypass access gates.'
        $text.Text=$lines -join "`r`n"
        $bottom=New-Object Windows.Forms.FlowLayoutPanel; $bottom.Dock='Bottom'; $bottom.Height=90
        $accept=New-Object Windows.Forms.CheckBox; $accept.Text='I reviewed the selected terms, have permission to use them, and approve these downloads.'; $accept.Width=760; $accept.Height=32
        $continue=New-Object Windows.Forms.Button; $continue.Text='Download selected'; $continue.Width=160; $continue.Enabled=$false; $continue.DialogResult='OK'
        $back=New-Object Windows.Forms.Button; $back.Text='Back'; $back.DialogResult='Cancel'
        $accept.Add_CheckedChanged({$continue.Enabled=$accept.Checked}); $bottom.Controls.AddRange(@($accept,$continue,$back)); $review.Controls.Add($text);$review.Controls.Add($bottom); $review.CancelButton=$back
        $approved=$review.ShowDialog($form) -eq 'OK'; $review.Dispose()
        if(-not $approved){return}
        foreach($folder in 'temp','logs'){New-Item -ItemType Directory -Path (Join-Path $studioRoot $folder) -Force | Out-Null}
        $selection=Join-Path $studioRoot 'temp/setup-selection.json'
        ConvertTo-Json -InputObject $ids | Set-Content -LiteralPath $selection
        $consent=Join-Path $studioRoot 'temp/setup-consent.json'
        @{acknowledged=$true;selected=$ids;catalogSha256=(Get-FileHash (Join-Path $PSScriptRoot 'catalog.json')).Hash;reviewedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $consent
        $install.Enabled=$false; $choices.Enabled=$false; $refresh.Enabled=$false; $cancel.Enabled=$true; $open.Enabled=$false
        $progress.Text='Starting setup...'
        $script:worker=Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'Install.ps1')+'"'),'-SelectionFile',('"'+$selection+'"'),'-ConsentFile',('"'+$consent+'"') -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError $errlog
        $null=$script:worker.Handle # Keep ExitCode available after a redirected Windows PowerShell child exits.
        $timer.Start()
    } catch { $progress.Text=$_.Exception.Message; $install.Enabled=$true; $choices.Enabled=$true; $refresh.Enabled=$true; $cancel.Enabled=$false; $open.Enabled=$true }
})
$stopWorker={
    if($script:worker -and -not $script:worker.HasExited){& taskkill.exe /PID $script:worker.Id /T /F | Out-Null}
}
$cancel.Add_Click($stopWorker)
$form.Add_FormClosing({param($sender,$eventArgs)
    if($script:worker -and -not $script:worker.HasExited){
        if([Windows.Forms.MessageBox]::Show('Pause downloads and close setup? Run Setup again to resume.','Downloads running','YesNo','Question') -ne 'Yes'){$eventArgs.Cancel=$true;return}
        & $stopWorker
    }
})
if($SmokeTest){
    if(@($checks | Where-Object Checked).Count -ne 0){throw 'A model was unexpectedly preselected.'}
    if($checks.Count -ne $catalog.bundles.Count){throw 'Model choices are missing.'}
    $form.StartPosition='Manual'; $form.Location=New-Object Drawing.Point(-10000,-10000)
    $form.Show(); [Windows.Forms.Application]::DoEvents(); $form.PerformLayout()
    if($ScreenshotPath){
        $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
        $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
        $bitmap.Save($ScreenshotPath,[Drawing.Imaging.ImageFormat]::Png); $bitmap.Dispose()
    }
    Write-Output "Setup controls constructed; $($checks.Count) optional choices, none preselected. No install/download action invoked."
}else{[void]$form.ShowDialog()}
$timer.Dispose(); $tips.Dispose(); $form.Dispose()
