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
# 2026-09-08：改用同資料夾的 pythonw.exe（無主控台視窗版本）取代 python.exe，
# 排程每15分鐘觸發一次、6小時內共24次，用一般python.exe每次都會跳出一個終端機
# 視窗，非常擾人（Cody反映過）。這兩支排程模式(intraday/close)全程只用logging
# 寫檔(logs/scheduler.log)，沒有print()到stdout（test-notify那個互動用的例外，
# 但那支是Cody自己在終端機手動打指令執行，不受這裡影響），改pythonw.exe安全。
$PythonwPath = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"
if (-not (Test-Path $PythonwPath)) {
    Write-Warning "找不到 $PythonwPath，退回用 python.exe（排程觸發時會跳出終端機視窗）"
    $PythonwPath = $PythonPath
}
$RunnerPath = Join-Path $ProjectRoot "scripts\run_scheduled.py"

if (-not (Test-Path $RunnerPath)) {
    Write-Error "找不到 $RunnerPath，請確認在專案根目錄執行，且 scripts/run_scheduled.py 已存在"
    exit 1
}

# ── 盤中監控 ──────────────────────────────────────────────
$IntradayAction = New-ScheduledTaskAction -Execute $PythonwPath `
    -Argument "`"$RunnerPath`" intraday" -WorkingDirectory $ProjectRoot

# New-ScheduledTaskTrigger -Once + -Repetition* 只會在建立當天重複觸發，之後永遠不再
# 觸發（-Once 本質上就是單次時間觸發，Repetition 只套用在那一次觸發的區間內）。
# -Daily/-Weekly trigger 又直接拒絕 -RepetitionInterval/-RepetitionDuration 參數，
# 所以先建一個會每天重複觸發的 -Weekly trigger，再把 -Once trigger 產生的 Repetition
# 物件接到它身上，讓「每天 09:00 開始、每15分鐘重複6小時」變成每個交易日都會發生。
# 2026-09-07：重複時長從4h45m(09:00-13:45)拉長到6h(09:00-15:00)，配合
# run_scheduled.py::is_market_hours()同步拉長的視窗，13:30 TWSE正式收盤後到15:00
# 收盤摘要之間不再是空窗期，多一層監控緩衝（intraday模式冪等，訊號沒變不會重複通知）。
$IntradayTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:00"
$rep = (New-ScheduledTaskTrigger -Once -At "09:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 6)).Repetition
$IntradayTrigger.Repetition = $rep

$IntradaySettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun

Register-ScheduledTask -TaskName "TW-Sector-Intraday" `
    -Action $IntradayAction -Trigger $IntradayTrigger -Settings $IntradaySettings `
    -Description "台股盤中籌碼監控，每15分鐘執行一次（09:00-15:00）" -Force

Write-Host "已建立 TW-Sector-Intraday"

# ── 收盤更新 ──────────────────────────────────────────────
$CloseAction = New-ScheduledTaskAction -Execute $PythonwPath `
    -Argument "`"$RunnerPath`" close" -WorkingDirectory $ProjectRoot

$CloseTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:00"

$CloseSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun

Register-ScheduledTask -TaskName "TW-Sector-DailyClose" `
    -Action $CloseAction -Trigger $CloseTrigger -Settings $CloseSettings `
    -Description "台股收盤每日更新，週一至週五 15:00 執行" -Force

Write-Host "已建立 TW-Sector-DailyClose"
Write-Host ""
Write-Host "驗收步驟（docs/scheduler.md §11.2）："
Write-Host "  1. python scripts/run_scheduled.py test-notify   （手機應收到測試訊息）"
Write-Host "  2. python scripts/run_scheduled.py intraday      （確認不產生 git commit）"
Write-Host "  3. Get-ScheduledTask -TaskName TW-Sector-* | Format-List"
