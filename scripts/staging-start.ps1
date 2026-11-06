$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PRAMANA_STAGING_PUBLIC_ORIGIN = 'https://pramana-staging.pramana-staging-worker.workers.dev'

if (-not $env:PG_BIN) {
    $pgBin = Join-Path $env:USERPROFILE 'scoop\apps\postgresql\current\bin'
    if (Test-Path -LiteralPath (Join-Path $pgBin 'pg_ctl.exe')) {
        $env:PG_BIN = $pgBin
    }
}

uv run python scripts/staging.py --fake-gnani
exit $LASTEXITCODE
