@echo off
REM Interactive setup for the Claude Usage collector (self-elevates for VSS).

REM --- self-elevate ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ==================================================
echo    Claude Usage Collector - setup
echo ==================================================
echo.
echo How often should it collect your usage?
echo    1. Minutes
echo    2. Hours
echo    3. Days
echo    4. Weeks
echo.
set "UNIT="
set /p CHOICE="Select 1-4: "
if "%CHOICE%"=="1" set "UNIT=minutes"
if "%CHOICE%"=="2" set "UNIT=hours"
if "%CHOICE%"=="3" set "UNIT=days"
if "%CHOICE%"=="4" set "UNIT=weeks"
if "!UNIT!"=="" (
    echo Invalid choice.
    pause
    exit /b 1
)

set "NUM="
set /p NUM="Every how many !UNIT!? "
if "!NUM!"=="" set "NUM=1"

set "AT=18:00"
if /i "!UNIT!"=="days"  set /p AT="At what time of day (HH:MM) [18:00]? "
if /i "!UNIT!"=="weeks" set /p AT="At what time of day (HH:MM) [18:00]? "
if "!AT!"=="" set "AT=18:00"

echo.
echo Test run...
ClaudeUsage.exe
echo.
echo Scheduling: every !NUM! !UNIT! ^(time !AT! for days/weeks^)...
ClaudeUsage.exe --install-task --every !NUM! --unit !UNIT! --at !AT!
echo.
pause
