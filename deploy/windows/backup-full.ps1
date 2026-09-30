[CmdletBinding()]
param([switch]$Secondary)
. (Join-Path $PSScriptRoot 'local-node-common.ps1')
try {
    Set-Location -LiteralPath $ProjectRoot
    Set-LocalNodeEnvironment
    $OperationArguments = @('manage.py', 'backup_full')
    if ($Secondary) { $OperationArguments += '--secondary' }
    Invoke-LocalPython -Arguments $OperationArguments
    exit 0
} catch {
    Write-Error 'La tarea operativa no terminó. Revisa el diagnóstico sin compartir secretos.' -ErrorAction Continue
    exit 1
}
