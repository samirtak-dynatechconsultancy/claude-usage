# Build ClaudeUsage.exe (single file) with PyInstaller.
# Run from this folder in a normal PowerShell:  .\build.ps1

# 1) deps (build machine only)
pip install pyinstaller supabase pycryptodome pywin32

# 2) build. --collect-all pulls in the dynamically-imported supabase stack;
#    the win32 hidden-imports cover pywin32's DPAPI / file / VSS calls.
pyinstaller --onefile --name ClaudeUsage `
  --collect-all supabase `
  --collect-all postgrest `
  --collect-all gotrue `
  --collect-all realtime `
  --collect-all storage3 `
  --collect-all supafunc `
  --collect-all httpx `
  --collect-all httpcore `
  --hidden-import win32crypt `
  --hidden-import win32file `
  --hidden-import win32timezone `
  desktop_usage.py

Write-Host ""
Write-Host "Built: dist\ClaudeUsage.exe" -ForegroundColor Green
Write-Host "Deploy that exe together with a .env file in the same folder." -ForegroundColor Green
