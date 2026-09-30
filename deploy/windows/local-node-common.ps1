Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$PythonExe = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$EnvFile = Join-Path $ProjectRoot '.env.local-node'

function Set-LocalNodeEnvironment {
    if (-not (Test-Path -LiteralPath $EnvFile)) { throw 'Copia y completa .env.local-node antes de continuar.' }
    # python-dotenv reads this exact file; do not evaluate its content as PowerShell.
    $env:BIGPARTY_ENV_FILE = $EnvFile
    $env:DJANGO_SETTINGS_MODULE = 'config.settings.local_node'
    $env:DEPLOYMENT_MODE = 'local_node'
}

function Invoke-LocalPython {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python terminó con código $LASTEXITCODE." }
}
