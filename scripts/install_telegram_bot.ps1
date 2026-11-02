<#
建立 Windows 工作排程 TW-Sector-TelegramBot：登入時啟動 Telegram 查股常駐程式（scripts/telegram_bot.py）。
2026-11-02 Cody 要求。程式當掉每 1 分鐘自動重啟；不設執行時間上限；插電與否都跑。

用法：以系統管理員權限開 PowerShell，在專案根目錄執行：
    .\scripts\install_telegram_bot.ps1
裝完會立刻啟動一次，之後每次登入自動啟動。只建立排程，不會動 Git 或資料。
#>

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = (Get-Command python).Source
$PythonwPath = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"   # 無主控台視窗版本，同 install_scheduler.ps1
if (-not (Test-Path $PythonwPath)) {
    Write-Warning "找不到 $PythonwPath，退回用 python.exe（會多一個終端機視窗）"
    $PythonwPath = $PythonPath
}
$BotPath = Join-Path $ProjectRoot "scripts\telegram_bot.py"
if (-not (Test-Path $BotPath)) {
    Write-Error "找不到 $BotPath，請確認在專案根目錄執行"
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $PythonwPath -Argument "`"$BotPath`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "TW-Sector-TelegramBot" `
    -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Telegram 查股常駐程式（只回 TELEGRAM_CHAT_ID），登入時啟動" -Force

Start-ScheduledTask -TaskName "TW-Sector-TelegramBot"
Write-Host "已建立並啟動 TW-Sector-TelegramBot"
Write-Host "驗收：在 Telegram 對 bot 打 3147，幾秒內應收到回覆；紀錄在 logs\telegram_bot.log"
