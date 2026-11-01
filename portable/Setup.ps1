$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$studioRoot = Split-Path $PSScriptRoot
$catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$hardware = Get-StudioHardware
$script:worker = $null
$form = New-Object Windows.Forms.Form
$form.Text = 'Image Studio — Portable Setup'
$form.Size = New-Object Drawing.Size(860,780)
$form.MinimumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI',10)
$form.BackColor = [Drawing.Color]::White
$layout = New-Object Windows.Forms.TableLayoutPanel
$layout.Dock = 'Fill'; $layout.AutoScroll=$true; $layout.Padding = New-Object Windows.Forms.Padding(22); $layout.ColumnCount=1; $layout.RowCount=7
foreach ($height in 54,46,320,42,38,115,50) { $layout.RowStyles.Add((New-Object Windows.Forms.RowStyle([Windows.Forms.SizeType]::Absolute,$height))) | Out-Null }
$form.Controls.Add($layout)
$heading = New-Object Windows.Forms.Label
$heading.Text='Choose what to download'; $heading.Font=New-Object Drawing.Font('Segoe UI',20,[Drawing.FontStyle]::Bold); $heading.Dock='Fill'
$layout.Controls.Add($heading,0,0)
$machine=New-Object Windows.Forms.Label
$machine.Text="$($hardware.GpuName) · $($hardware.VramGB) GB VRAM · $($hardware.RamGB) GB RAM`nEverything stays in this folder. No administrator access or separate Python/.NET installation."
$machine.Dock='Fill'; $layout.Controls.Add($machine,0,1)
$choices=New-Object Windows.Forms.FlowLayoutPanel
$choices.Dock='Fill'; $choices.FlowDirection='TopDown'; $choices.WrapContents=$false; $choices.AutoScroll=$true
$layout.Controls.Add($choices,0,2)
$checks=@()
$tips=New-Object Windows.Forms.ToolTip
foreach ($bundle in $catalog.bundles) {
    $check=New-Object Windows.Forms.CheckBox
    $check.AutoSize=$false; $check.Width=760; $check.Height=44; $check.Tag=$bundle.id
    $reason=Get-StudioCompatibility $bundle $hardware
    $check.Text="$($bundle.title) — $([math]::Round($bundle.bytes/1e9,1)) GB`n"+$(if($reason){$reason}else{$bundle.description})
    $check.Enabled=[string]::IsNullOrEmpty($reason); $check.Checked=$check.Enabled -and $bundle.recommended
    $tips.SetToolTip($check,($bundle.description+"`nLicense: "+$bundle.licenseUrl))
    $choices.Controls.Add($check); $checks += $check
}
$total=New-Object Windows.Forms.Label; $total.Dock='Fill'; $layout.Controls.Add($total,0,3)
$refreshTotal={
    $ids=@($checks | Where-Object Checked | ForEach-Object Tag)
    $bytes=$catalog.engine.bytes+($catalog.bundles | Where-Object {$_.id -in $ids} | Measure-Object bytes -Sum).Sum
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
$actions.Controls.AddRange(@($install,$cancel,$open)); $layout.Controls.Add($actions,0,6)
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
        $timer.Stop(); $install.Enabled=$true; $choices.Enabled=$true; $cancel.Enabled=$false; $open.Enabled=$true
        if($script:worker.ExitCode -ne 0){$progress.AppendText("`r`nSetup stopped. Fix the message above, then Install selected again to resume. See logs/setup-errors.log for download details.")}
        $script:worker.Dispose(); $script:worker=$null
    }
})
$install.Add_Click({
    try {
        if($studioRoot.StartsWith('\\')){throw 'Extract the package to a local drive before installing.'}
        $ids=@($checks | Where-Object Checked | ForEach-Object Tag)
        $reason=Get-StudioCompatibility ([pscustomobject]@{minRamGB=16;minVramGB=8}) $hardware
        if($reason){throw $reason}
        $script:downloadEntries=@(Get-StudioPlan $catalog $ids $hardware)
        foreach($folder in 'temp','logs'){New-Item -ItemType Directory -Path (Join-Path $studioRoot $folder) -Force | Out-Null}
        $selection=Join-Path $studioRoot 'temp/setup-selection.json'
        ConvertTo-Json -InputObject $ids | Set-Content -LiteralPath $selection
        $install.Enabled=$false; $choices.Enabled=$false; $cancel.Enabled=$true; $open.Enabled=$false
        $progress.Text='Starting setup...'
        $script:worker=Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'Install.ps1')+'"'),'-SelectionFile',('"'+$selection+'"') -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError $errlog
        $null=$script:worker.Handle # Keep ExitCode available after a redirected Windows PowerShell child exits.
        $timer.Start()
    } catch { $progress.Text=$_.Exception.Message; $install.Enabled=$true; $choices.Enabled=$true; $cancel.Enabled=$false; $open.Enabled=$true }
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
[void]$form.ShowDialog()
$timer.Dispose(); $tips.Dispose(); $form.Dispose()
