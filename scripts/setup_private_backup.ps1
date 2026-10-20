param([string]$Python = 'python', [string]$OutputDirectory = "$env:LOCALAPPDATA\GameArena\Backups", [string]$PostgresBin = '', [switch]$ConfigureOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$privateDirectory = Join-Path $env:LOCALAPPDATA 'GameArena\BackupConfig'
New-Item -ItemType Directory -Path $privateDirectory -Force | Out-Null
$settings = [pscustomobject]@{
    Database = Read-Host 'Backup database URL (private; hidden)' -AsSecureString
    Key = Read-Host 'Backup encryption key (private; hidden)' -AsSecureString
    Python = (Get-Command $Python -ErrorAction Stop).Source
    Output = [IO.Path]::GetFullPath($OutputDirectory)
    Project = $projectRoot
    PostgresBin = $PostgresBin
}
# DPAPI binds these encrypted values to this Windows user on this computer.
$settings | Export-Clixml -LiteralPath (Join-Path $privateDirectory 'settings.clixml')
if (!$ConfigureOnly) {
    $runner = Join-Path $PSScriptRoot 'run_private_backup.ps1'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"')
    $trigger = New-ScheduledTaskTrigger -Daily -At '03:00'
    $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName 'GameArena encrypted database backup' -Action $action -Trigger $trigger -Settings $taskSettings -Principal $principal -Force | Out-Null
    Write-Host 'Daily backup scheduled for 03:00 using the computer timezone. This user must be signed in and the computer available.'
}
Write-Host 'Private configuration saved. Keep a separate safe copy of your encryption key; losing it makes backups unrecoverable.'
