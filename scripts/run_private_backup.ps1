$ErrorActionPreference = 'Stop'
$configuration = Join-Path $env:LOCALAPPDATA 'GameArena\BackupConfig\settings.clixml'
if (!(Test-Path -LiteralPath $configuration)) { throw 'Run setup_private_backup.ps1 privately before starting backups.' }
$settings = Import-Clixml -LiteralPath $configuration
function Get-PrivateValue($secureValue) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
try {
    $env:GAMEARENA_BACKUP_DATABASE_URL = Get-PrivateValue $settings.Database
    $env:GAMEARENA_BACKUP_KEY = Get-PrivateValue $settings.Key
    if ($settings.PostgresBin) { $env:GAMEARENA_PG_BIN = $settings.PostgresBin }
    New-Item -ItemType Directory -Path $settings.Output -Force | Out-Null
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $destination = Join-Path $settings.Output ('gamearena-' + $stamp + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.gabk')
    & $settings.Python (Join-Path $settings.Project 'scripts\backup_database.py') backup --output $destination
    if ($LASTEXITCODE -ne 0) { throw 'Encrypted backup failed. No plaintext database dump was retained.' }
    & $settings.Python (Join-Path $settings.Project 'scripts\backup_database.py') verify $destination
    if ($LASTEXITCODE -ne 0) { throw 'Backup archive verification failed.' }
} finally {
    Remove-Item Env:GAMEARENA_BACKUP_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:GAMEARENA_BACKUP_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:GAMEARENA_PG_BIN -ErrorAction SilentlyContinue
}
