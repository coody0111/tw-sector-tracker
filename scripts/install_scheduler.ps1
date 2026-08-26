<#
建立 Windows 工作排程器的兩個排程工作：TW-Sector-Intraday（盤中每15分鐘）、
TW-Sector-DailyClose（收盤 15:00）。見 docs/scheduler.md §10。

用法：以系統管理員權限開 PowerShell，執行：
    .\scripts\install_scheduler.ps1

只建立排程工作，不會立即執行 main.py，也不會動 Git。
#>

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = (Get-Command python).Source
$RunnerPath = Join-Path $ProjectRoot "scripts\run_scheduled.py"

if (-not (Test-Path $RunnerPath)) {
    Write-Error "找不到 $RunnerPath，請確認在專案根目錄執行，且 scripts/run_scheduled.py 已存在"
    exit 1
}

# ── 盤中監控 ──────────────────────────────────────────────
$IntradayAction = New-ScheduledTaskAction -Execute $PythonPath `
    -Argument "`"$RunnerPath`" intraday" -WorkingDirectory $ProjectRoot

$IntradayTrigger = New-ScheduledTaskTrigger -Once -At "09:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 4 -Minutes 45)

$IntradaySettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName "TW-Sector-Intraday" `
    -Action $IntradayAction -Trigger $IntradayTrigger -Settings $IntradaySettings `
    -Description "台股盤中籌碼監控，每15分鐘執行一次（09:00-13:45）" -Force

Write-Host "已建立 TW-Sector-Intraday"

# ── 收盤更新 ──────────────────────────────────────────────
$CloseAction = New-ScheduledTaskAction -Execute $PythonPath `
    -Argument "`"$RunnerPath`" close" -WorkingDirectory $ProjectRoot

$CloseTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:00"

$CloseSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName "TW-Sector-DailyClose" `
    -Action $CloseAction -Trigger $CloseTrigger -Settings $CloseSettings `
    -Description "台股收盤每日更新，週一至週五 15:00 執行" -Force

Write-Host "已建立 TW-Sector-DailyClose"
Write-Host ""
Write-Host "驗收步驟（docs/scheduler.md §11.2）："
Write-Host "  1. python scripts/run_scheduled.py test-notify   （手機應收到測試訊息）"
Write-Host "  2. python scripts/run_scheduled.py intraday      （確認不產生 git commit）"
Write-Host "  3. Get-ScheduledTask -TaskName TW-Sector-* | Format-List"
