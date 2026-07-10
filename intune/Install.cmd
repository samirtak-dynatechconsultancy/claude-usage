@echo off
REM Intune Win32 install command (runs as SYSTEM).
REM Copies the app to a permanent location and registers the daily task to run
REM as the logged-on user (elevated). Requires users to be local admins (VSS).
setlocal
set "DEST=%ProgramData%\ClaudeUsage"

if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0ClaudeUsage.exe" "%DEST%\" >nul
copy /y "%~dp0.env"            "%DEST%\" >nul

REM Let the logged-on user (BUILTIN\Users) write usage.csv in the install dir.
icacls "%DEST%" /grant *S-1-5-32-545:(OI)(CI)M >nul 2>&1

REM Register the scheduled task (daily 18:00 + at logon, catch-up, wake).
"%DEST%\ClaudeUsage.exe" --install-task-allusers 18:00
set RC=%ERRORLEVEL%

endlocal & exit /b %RC%
