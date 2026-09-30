[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    Set-LocalNodeEnvironment
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Ejecuta primero el instalador.' }
    Invoke-LocalPython -Arguments @('manage.py', 'sync_worker')
    exit 0
} catch {
    Write-Error 'El proceso de sincronización terminó. Revisa check-sync y PostgreSQL.' -ErrorAction Continue
    exit 1
}
