@echo off
REM Removes the daily Claude Usage scheduled task (elevates itself).

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo Removing the scheduled task...
ClaudeUsage.exe --uninstall-task
echo.
echo Uninstalled. (The exe and files remain; delete this folder to remove them.)
pause
