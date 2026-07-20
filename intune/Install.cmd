@echo off
REM Intune Win32 install command (runs as SYSTEM).
REM Copies the app to a permanent location and registers a SYSTEM-context task
REM that reads the logged-on user's usage. Works for STANDARD (non-admin) users:
REM the SYSTEM task holds the elevation (VSS); it briefly impersonates the user
REM only to unwrap their cookie key.
setlocal
set "DEST=%ProgramData%\ClaudeUsage"

if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0ClaudeUsage.exe" "%DEST%\" >nul
copy /y "%~dp0.env"            "%DEST%\" >nul

REM Register the daily task for the logged-on user (requires that user to be a
REM local admin, since VSS needs elevation). Standard-user/SYSTEM mode was
REM intentionally removed; see INTUNE.md.
"%DEST%\ClaudeUsage.exe" --install-task-allusers 18:00
set RC=%ERRORLEVEL%

endlocal & exit /b %RC%
