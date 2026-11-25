@echo off
chcp 65001 >nul
rem ASCII only: cmd reads .bat in the console code page (cp950 here), so UTF-8 Chinese
rem mis-splits lines and runs fragments as commands. tests/test_bat_files.py enforces this.
echo === End of day (check only, no commit / no push) ===
echo.

rem Project folder = where this .bat lives (no hard-coded machine path)
cd /d "%~dp0"

rem Since 2026-11-26 this no longer commits or pushes: master only takes dev after Debugger OK
rem (the git hook blocks it too). Commit code in the dev folder: dev, Debugger, publish to master.
echo [1/3] This folder:
git branch --show-current
git status --short
echo.

echo [2/3] All three folders (anything not committed?):
for %%W in (tw-sector-tracker tw-sector-tracker-dev tw-sector-tracker-debug) do (
    if exist "..\%%W\.git" (
        echo --- %%W
        git -C "..\%%W" status --short --branch
    )
)
echo.

echo [3/3] dev commits not yet published to master:
git log --oneline master..dev
echo.
echo Uncommitted changes: commit them in the dev folder (git add the files, never git add .)
echo New dev commits: hand to Debugger; publish to master only after all OK (CLAUDE.md "publish to master")
echo.
pause
