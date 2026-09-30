[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    Set-LocalNodeEnvironment
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Ejecuta primero el instalador.' }
    Invoke-LocalPython -Arguments @('manage.py', 'check_local_node')
    exit 0
} catch {
    Write-Error 'El diagnóstico no se completó correctamente.' -ErrorAction Continue
    exit 1
}
