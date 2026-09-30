# Run once dependencies are available; rerunnable without deleting data.
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot '.env.local-node.example') -Destination $EnvFile
        Write-Host 'Se creó .env.local-node. Completa secretos, base y hostname; vuelve a ejecutar este instalador.'
        exit 1
    }
    Set-LocalNodeEnvironment
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        & py -3.13 -m venv (Join-Path $ProjectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python 3.13.' }
    }
    Invoke-LocalPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $ProjectRoot 'requirements/prod.txt'))
    Invoke-LocalPython -Arguments @('manage.py', 'check')
    Invoke-LocalPython -Arguments @('manage.py', 'migrate', '--noinput')
    Invoke-LocalPython -Arguments @('manage.py', 'collectstatic', '--noinput')
    Invoke-LocalPython -Arguments @('manage.py', 'prepare_local_node')
    Invoke-LocalPython -Arguments @('manage.py', 'check_local_node')
    Write-Host 'Nodo preparado. Crea usuarios autorizados y configura impresoras antes de operar.'
    exit 0
} catch {
    Write-Error 'Instalación incompleta. Revisa el paso que falló y la guía LOCAL-NODE-WINDOWS.' -ErrorAction Continue
    exit 1
}
