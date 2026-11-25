# Ejecuta manage.py con la configuración de producción instalada, como el
# comando `siga` de la guía de Linux. Úselo desde PowerShell como administrador:
#   & "C:\Program Files\SIGA-MINEDUCYT\deploy\windows\siga.ps1" deployment_preflight
#   & "C:\Program Files\SIGA-MINEDUCYT\deploy\windows\siga.ps1" import_center_emails C:\carga\Listado.xlsx --dry-run
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")

$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecute PowerShell como administrador: la configuración solo es legible por administradores."
}

Import-SigaEnvironment | Out-Null
Push-Location -LiteralPath $SigaAppRoot
try {
    & $SigaPython $SigaManage @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
