@echo off
echo === tw-sector-tracker 桌電啟動 ===
echo.

:: 專案位置 = 這支 bat 所在目錄，不寫死機器路徑；
:: 下面 start 開出來的視窗會繼承這個工作目錄
cd /d "%~dp0"

:: 同步最新 code
echo [1/3] 同步最新 code...
git pull origin master
echo      完成
echo.

:: 啟動 Developer
echo [2/3] 啟動 Developer...
start "Developer" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-developer && copy /Y CLAUDE-developer.md CLAUDE.md >nul && claude"

:: 啟動 Debugger（debug worktree 固定在專案的同層目錄）
echo [3/3] 啟動 Debugger...
start "Debugger" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-debugger && cd /d ..\tw-sector-tracker-debug && copy /Y CLAUDE-debugger.md CLAUDE.md >nul && claude"

echo.
echo 兩個 agent 已啟動！
echo 各跟他們說：「讀 CLAUDE.md，告訴我目前狀態」
