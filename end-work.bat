@echo off
echo === 下班收工 ===
echo.

:: 專案位置 = 這支 bat 所在目錄，不再依機器寫死絕對路徑
cd /d "%~dp0"

echo [1/2] 目前未 commit 的變更：
git status --short
echo.

echo [2/2] Commit + Push...
git add .
set /p MSG="Commit 訊息（直接 Enter 跳過）: "
if "%MSG%"=="" (
    echo 跳過 commit
) else (
    git commit -m "%MSG%"
    git push origin master
    echo      完成！
)
echo.
pause
