@echo off
chcp 65001 >nul
echo === 下班收工（只檢查，不 commit、不 push）===
echo.

:: 專案位置 = 這支 bat 所在目錄，不再依機器寫死絕對路徑
cd /d "%~dp0"

:: 2026-11-26 起不再 git add . + push master：master 只收 Debugger 驗過的 dev（git hook 也會擋），
:: 程式改動在 dev 資料夾 commit，走「dev → Debugger → 發佈到 master」。
echo [1/3] 這個資料夾：
git branch --show-current
git status --short
echo.

echo [2/3] 三個資料夾（有沒有忘了 commit 的東西）：
for %%W in (tw-sector-tracker tw-sector-tracker-dev tw-sector-tracker-debug) do (
    if exist "..\%%W\.git" (
        echo --- %%W
        git -C "..\%%W" status --short --branch
    )
)
echo.

echo [3/3] 還沒發佈到 master 的 dev commit：
git log --oneline master..dev
echo.
echo 有東西沒 commit：到 dev 資料夾 commit（git add 指定檔案，不要 git add .）
echo dev 有新 commit：交給 Debugger，全部 ✅ 才發佈到 master（見 CLAUDE.md「發佈到 master」）
echo.
pause
