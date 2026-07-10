@echo off
REM Installs the daily Claude Usage collector (elevates itself for VSS).
REM Default time 18:00; pass another as:  install.bat 20:30

set TIME_ARG=%1
if "%TIME_ARG%"=="" set TIME_ARG=18:00

REM Re-launch elevated if not already admin.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -ArgumentList '%TIME_ARG%' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo Running a test read + Supabase push...
ClaudeUsage.exe
echo.
echo Installing daily scheduled task at %TIME_ARG% ...
ClaudeUsage.exe --install-task %TIME_ARG%
echo.
echo Done. The collector runs every day at %TIME_ARG%.
pause
