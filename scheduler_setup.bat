@echo off
REM 設定 Windows Task Scheduler，每天 14:35 執行爬蟲
REM 以系統管理員身分執行此 bat 檔

set TASK_NAME=TW-Sector-Tracker
set PYTHON_PATH=python
set SCRIPT_PATH=C:\Users\Cody\Desktop\tw-sector-tracker\main.py

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "%PYTHON_PATH% %SCRIPT_PATH%" ^
  /sc DAILY ^
  /st 14:35 ^
  /sd 2026/06/01 ^
  /ru "%USERNAME%" ^
  /f

echo Task created. Verify with: schtasks /query /tn "%TASK_NAME%"
