$ErrorActionPreference = 'Stop'
$taskName = 'PramanaStaging'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output "Task $taskName is not registered."
    exit 0
}
if ($task.State -eq 'Running') {
    throw 'Stop the staging supervisor with Ctrl+C in its console, then run this script again.'
}

Unregister-ScheduledTask -InputObject $task -Confirm:$false
Write-Output "Removed $taskName. The shared PostgreSQL cluster and its databases were left alone."
