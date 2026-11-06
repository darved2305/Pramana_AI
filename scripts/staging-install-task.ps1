$ErrorActionPreference = 'Stop'
$taskName = 'PramanaStaging'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    throw "Task $taskName already exists. Remove it with scripts/staging-uninstall-task.ps1 first."
}

$startup = Join-Path $PSScriptRoot 'staging-start.ps1'
$powershell = (Get-Process -Id $PID).Path
if (-not (Test-Path -LiteralPath $powershell)) {
    throw 'Could not resolve the current PowerShell executable.'
}
$arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$startup`""
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Start the Pramana staging supervisor when this user logs in.' | Out-Null

Write-Output "Registered $taskName for $user. The supervisor console opens at logon."
