[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    Set-LocalNodeEnvironment
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Ejecuta primero el instalador.' }
    Invoke-LocalPython -Arguments @('-m', 'apps.localnode.runtime')
    exit 0
} catch {
    Write-Error 'No se pudo iniciar el nodo. Revisa el diagnóstico y PostgreSQL.' -ErrorAction Continue
    exit 1
}
