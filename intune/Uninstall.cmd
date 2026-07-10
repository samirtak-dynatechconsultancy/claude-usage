@echo off
REM Intune Win32 uninstall command (runs as SYSTEM).
setlocal
set "DEST=%ProgramData%\ClaudeUsage"

if exist "%DEST%\ClaudeUsage.exe" "%DEST%\ClaudeUsage.exe" --uninstall-task
schtasks /delete /tn "ClaudeUsageDaily" /f >nul 2>&1
rmdir /s /q "%DEST%" 2>nul

endlocal & exit /b 0
