# Intune Win32 detection script.
# "Installed" = the scheduled task exists (exit 0 + stdout). Otherwise exit 1.
if (Get-ScheduledTask -TaskName 'ClaudeUsageDaily' -ErrorAction SilentlyContinue) {
    Write-Output 'ClaudeUsageDaily present'
    exit 0
}
exit 1
