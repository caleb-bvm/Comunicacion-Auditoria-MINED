# Ejecutado por las tareas programadas que registra instalar-servidor.ps1.
#   web             Waitress en 127.0.0.1 detrás de IIS (LOCAL SERVICE, al iniciar Windows)
#   overdue         process_overdue_recommendations (diario)
#   verify-storage  verify_private_storage --checksums (semanal)
#   backup          pg_dump diario con 14 días de retención (SYSTEM)
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("web", "overdue", "verify-storage", "backup")]
    [string]$Mode,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Set-SigaUtf8Console

$logPath = Join-Path $SigaLogRoot "$Mode.log"

function Write-ServiceLog {
    param([string]$Message)
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" -Encoding UTF8
}

function Invoke-LoggedPython {
    param([string[]]$Arguments)

    # La salida de error de Python no debe convertirse en excepción de PowerShell.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $SigaPython @Arguments 2>&1 | ForEach-Object { "$_" } |
            Out-File -LiteralPath $logPath -Append -Encoding utf8
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 10MB) {
    Move-Item -LiteralPath $logPath -Destination "$logPath.1" -Force
}

Set-Location -LiteralPath $SigaAppRoot
try {
    Import-SigaEnvironment | Out-Null
} catch {
    Write-ServiceLog "ERROR: $($_.Exception.Message)"
    exit 1
}

switch ($Mode) {
    "web" {
        # Al arrancar Windows, PostgreSQL y ClamAV pueden tardar varios minutos.
        $deadline = (Get-Date).AddMinutes(15)
        while ($true) {
            Write-ServiceLog "Comprobando base de datos, almacenamiento, antivirus y correo..."
            $code = Invoke-LoggedPython @($SigaManage, "deployment_preflight")
            if ($code -eq 0) {
                break
            }
            if ((Get-Date) -gt $deadline) {
                Write-ServiceLog "ERROR: la verificación previa no se completó en 15 minutos."
                exit 1
            }
            Start-Sleep -Seconds 30
        }

        # Si Waitress se detiene por cualquier causa, se reinicia tras una pausa breve.
        while ($true) {
            Write-ServiceLog "Iniciando Waitress en 127.0.0.1:$Port"
            $code = Invoke-LoggedPython @(
                "-m", "waitress",
                "--listen=127.0.0.1:$Port",
                "--threads=8",
                # Igual que IIS: 12 minutos (el antivirus puede tardar con PDF de 50 MB)
                # y 600 MB por envío (informe y diez adjuntos de 50 MB).
                "--channel-timeout=720",
                "--max-request-body-size=629145600",
                "--trusted-proxy=127.0.0.1",
                "--trusted-proxy-count=1",
                "--trusted-proxy-headers=x-forwarded-for x-forwarded-proto",
                "config.wsgi:application"
            )
            Write-ServiceLog "Waitress terminó con código $code; se reinicia en 10 segundos."
            Start-Sleep -Seconds 10
        }
    }
    "overdue" {
        exit (Invoke-LoggedPython @($SigaManage, "process_overdue_recommendations"))
    }
    "verify-storage" {
        exit (Invoke-LoggedPython @($SigaManage, "verify_private_storage", "--checksums"))
    }
    "backup" {
        try {
            $path = New-SigaDatabaseBackup -Prefix "diario" -KeepDays 14
            Write-ServiceLog "Respaldo verificado: $path"
        } catch {
            Write-ServiceLog "ERROR: $($_.Exception.Message)"
            exit 1
        }
    }
}
