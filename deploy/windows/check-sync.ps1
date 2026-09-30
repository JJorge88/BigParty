[CmdletBinding()]
param([switch]$Probe)
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    Set-LocalNodeEnvironment
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Ejecuta primero el instalador.' }
    $SyncArguments = @('manage.py', 'check_sync')
    if ($Probe) { $SyncArguments += '--probe' }
    Invoke-LocalPython -Arguments $SyncArguments
    exit 0
} catch {
    Write-Error 'Diagnóstico de sincronización incompleto. El POS utiliza su proceso separado.' -ErrorAction Continue
    exit 1
}
