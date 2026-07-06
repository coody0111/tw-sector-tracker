@echo off
echo === tw-sector-tracker 桌電啟動 ===
echo.

:: 同步最新 code
echo [1/3] 同步最新 code...
cd C:\Users\Cody\Desktop\tw-sector-tracker
git pull origin master
echo      完成
echo.

:: 啟動 Developer
echo [2/3] 啟動 Developer...
start "Developer" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-developer && cd C:\Users\Cody\Desktop\tw-sector-tracker && copy /Y CLAUDE-developer.md CLAUDE.md >nul && claude"

:: 啟動 Debugger
echo [3/3] 啟動 Debugger...
start "Debugger" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-debugger && cd C:\Users\Cody\Desktop\tw-sector-tracker-debug && copy /Y CLAUDE-debugger.md CLAUDE.md >nul && claude"

echo.
echo 兩個 agent 已啟動！
echo 各跟他們說：「讀 CLAUDE.md，告訴我目前狀態」
