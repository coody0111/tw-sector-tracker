@echo off
chcp 65001 >nul
rem ASCII only: cmd reads .bat in the console code page (cp950 here), so UTF-8 Chinese
rem mis-splits lines and runs fragments as commands. tests/test_bat_files.py enforces this.
echo === tw-sector-tracker laptop start ===
echo.

rem Project folder = where this .bat lives (no hard-coded machine path);
rem the windows opened by start below inherit this working directory
cd /d "%~dp0"

rem Sync latest code
echo [1/3] Syncing latest code...
git pull origin master
echo      done
echo.

rem Start Developer
echo [2/3] Starting Developer...
start "Developer" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-developer && copy /Y CLAUDE-developer.md CLAUDE.md >nul && claude"

rem Start Debugger (debug worktree is always the sibling folder)
echo [3/3] Starting Debugger...
start "Debugger" cmd /k "set CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-debugger && cd /d ..\tw-sector-tracker-debug && copy /Y CLAUDE-debugger.md CLAUDE.md >nul && claude"

echo.
echo Both agents started.
echo Tell each one: read CLAUDE.md and report the current status
