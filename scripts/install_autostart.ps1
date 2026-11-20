# Windowsにログインしたら、自動仕分け（app.watch）を裏で起動するように登録する
# 実行: powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
# 解除: Unregister-ScheduledTask -TaskName "mail-sorter" -Confirm:$false

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"   # pythonw = 画面（黒い窓）を出さないPython

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "-m app.watch" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"   # ログインの1分後に起動（Ollamaやネットの準備を待つ）
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "mail-sorter" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Gmailを10分ごとに自動で仕分けする" -Force | Out-Null

Write-Host "登録しました。次回のログインから自動で動きます。今すぐ動かすには: Start-ScheduledTask -TaskName mail-sorter"
