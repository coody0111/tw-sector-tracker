@echo off
echo === 下班收工 ===
echo.

:: 判斷是哪台電腦
if exist "C:\Users\Cody\Desktop\tw-sector-tracker" (
    set PROJECT=C:\Users\Cody\Desktop\tw-sector-tracker
) else (
    set PROJECT=C:\Users\codyliu\Desktop\tw-sector-tracker
)

cd %PROJECT%
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
