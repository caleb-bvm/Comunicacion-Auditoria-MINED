# Funciones compartidas por el instalador, el servicio y siga.ps1 en Windows.
# Se carga con dot-sourcing; no ejecuta nada por sí mismo.

$SigaDataRoot = Join-Path $env:ProgramData "SIGA-MINEDUCYT"
$SigaAppRoot = Join-Path $env:ProgramFiles "SIGA-MINEDUCYT"
$SigaEnvPath = Join-Path $SigaDataRoot "production.env"
$SigaPrivateRoot = Join-Path $SigaDataRoot "private"
$SigaLogRoot = Join-Path $SigaDataRoot "logs"
$SigaBackupRoot = Join-Path $SigaDataRoot "backups"
$SigaWwwRoot = Join-Path $SigaDataRoot "wwwroot"
$SigaCertRoot = Join-Path $SigaDataRoot "certificado"
$SigaSecretsRoot = Join-Path $SigaDataRoot "secretos"
$SigaPython = Join-Path $SigaAppRoot ".venv\Scripts\python.exe"
$SigaManage = Join-Path $SigaAppRoot "manage.py"

function Set-SigaUtf8Console {
    # winget y Python (con PYTHONUTF8=1) escriben en UTF-8, pero Windows PowerShell 5.1
    # decodifica su salida con la página de códigos de la consola (850 en español), y
    # "ó" aparece como "├│". Sin consola (tareas programadas) el cambio puede fallar.
    $utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
    try { [Console]::OutputEncoding = $utf8 } catch { }
    $global:OutputEncoding = $utf8
}

function Read-SigaEnvFile {
    param([string]$Path = $SigaEnvPath)

    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    foreach ($rawLine in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $name, $value = $line.Split("=", 2)
        $values[$name.Trim()] = $value.Trim()
    }
    return $values
}

function Write-SigaEnvFile {
    param(
        [System.Collections.IDictionary]$Values,
        [string]$Path = $SigaEnvPath,
        [string]$Generator = "instalar-servidor.ps1"
    )

    $lines = @(
        "# Configuración de SIGA-MINEDUCYT generada por $Generator."
        "# Contiene secretos: no la comparta ni la copie a Git."
    )
    foreach ($name in $Values.Keys) {
        $lines += "$name=$($Values[$name])"
    }
    [System.IO.File]::WriteAllLines($Path, $lines, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
}

function Import-SigaEnvironment {
    $values = Read-SigaEnvFile
    if ($values.Count -eq 0) {
        throw "No existe la configuración $SigaEnvPath. Ejecute primero instalar-servidor.cmd."
    }
    foreach ($name in $values.Keys) {
        Set-Item -Path "Env:$name" -Value $values[$name]
    }
    $env:DJANGO_SETTINGS_MODULE = "config.settings.production"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONUTF8 = "1"
    return $values
}

function Test-SigaTcpPort {
    param([string]$HostName = "127.0.0.1", [int]$Port, [int]$TimeoutMs = 1000)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            return $false
        }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-SigaClamAV {
    param([int]$Port = 3310)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(2000)) {
            return $false
        }
        $client.EndConnect($pending)
        $stream = $client.GetStream()
        $stream.ReadTimeout = 5000
        $request = [System.Text.Encoding]::ASCII.GetBytes("zPING`0")
        $stream.Write($request, 0, $request.Length)
        $buffer = New-Object byte[] 16
        $read = $stream.Read($buffer, 0, $buffer.Length)
        return [System.Text.Encoding]::ASCII.GetString($buffer, 0, $read) -eq "PONG`0"
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-SigaPgBin {
    $root = Join-Path $env:ProgramFiles "PostgreSQL"
    if (-not (Test-Path -LiteralPath $root)) {
        return $null
    }
    $versions = Get-ChildItem -LiteralPath $root -Directory |
        Where-Object { $_.Name -match "^\d+$" -and (Test-Path (Join-Path $_.FullName "bin\pg_dump.exe")) } |
        Sort-Object { [int]$_.Name } -Descending
    if ($versions) {
        return Join-Path $versions[0].FullName "bin"
    }
    return $null
}

function New-SigaDatabaseBackup {
    param([string]$Prefix = "respaldo", [int]$KeepDays = 0)

    $pgBin = Get-SigaPgBin
    if (-not $pgBin) {
        throw "No se encontró pg_dump.exe de PostgreSQL."
    }
    New-Item -ItemType Directory -Force -Path $SigaBackupRoot | Out-Null
    $backupPath = Join-Path $SigaBackupRoot "$Prefix-$(Get-Date -Format 'yyyyMMdd-HHmmss').dump"
    $previousPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $env:POSTGRES_PASSWORD
        & (Join-Path $pgBin "pg_dump.exe") --no-password "--host=$env:POSTGRES_HOST" "--port=$env:POSTGRES_PORT" `
            "--username=$env:POSTGRES_USER" --format=custom "--file=$backupPath" "--dbname=$env:POSTGRES_DB"
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump terminó con código $LASTEXITCODE."
        }
        $listing = & (Join-Path $pgBin "pg_restore.exe") --list $backupPath
        if ($LASTEXITCODE -ne 0 -or -not $listing) {
            throw "pg_restore no pudo validar el respaldo."
        }
    } catch {
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        throw
    } finally {
        $env:PGPASSWORD = $previousPassword
    }

    if ($KeepDays -gt 0) {
        Get-ChildItem -LiteralPath $SigaBackupRoot -Filter "$Prefix-*.dump" |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
            Remove-Item -Force
    }
    return $backupPath
}

# ---------------------------------------------------------------------------
# Consola y utilidades del sistema
# ---------------------------------------------------------------------------

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK  $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "      $Message"
}

function Read-Value {
    param([string]$Prompt, [string]$Default = "", [switch]$AllowEmpty)
    while ($true) {
        $label = if ($Default) { "  $Prompt [$Default]" } else { "  $Prompt" }
        $answer = (Read-Host $label).Trim()
        if (-not $answer) {
            $answer = $Default
        }
        if ($answer -or $AllowEmpty) {
            return $answer
        }
        Write-Host "  Este dato es obligatorio." -ForegroundColor Yellow
    }
}

function Read-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    $hint = if ($Default) { "S/n" } else { "s/N" }
    while ($true) {
        $answer = (Read-Host "  $Prompt ($hint)").Trim().ToLowerInvariant()
        if (-not $answer) { return $Default }
        if ($answer -in @("s", "si", "sí", "y", "yes")) { return $true }
        if ($answer -in @("n", "no")) { return $false }
    }
}

function ConvertFrom-SecureText {
    param([Security.SecureString]$Secure)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Read-Secret {
    param([string]$Prompt, [switch]$Confirm, [switch]$AllowEmpty)
    while ($true) {
        $first = ConvertFrom-SecureText (Read-Host "  $Prompt" -AsSecureString)
        if (-not $first -and -not $AllowEmpty) {
            Write-Host "  Este dato es obligatorio." -ForegroundColor Yellow
            continue
        }
        if (-not $Confirm) {
            return $first
        }
        $second = ConvertFrom-SecureText (Read-Host "  Repita la contraseña" -AsSecureString)
        if ($first -ceq $second) {
            return $first
        }
        Write-Host "  Las contraseñas no coinciden. Inténtelo de nuevo." -ForegroundColor Yellow
    }
}

function New-RandomSecret {
    param([int]$Length = 32)
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "User")
}

function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments, [string]$Failure, [int[]]$AllowedCodes = @(0))
    & $FilePath @Arguments
    if ($AllowedCodes -notcontains $LASTEXITCODE) {
        throw "$Failure (código $LASTEXITCODE)"
    }
}

function Invoke-Icacls {
    param([string[]]$Arguments)
    & "$env:WINDIR\System32\icacls.exe" @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls no pudo aplicar permisos en $($Arguments[0]) (código $LASTEXITCODE)."
    }
}

function Get-Winget {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        # En un Windows recién instalado, winget existe pero aún no está registrado.
        Write-Info "Registrando winget (Instalador de aplicaciones)..."
        try {
            Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe
        } catch {
            Write-Info "No se pudo registrar automáticamente: $($_.Exception.Message)"
        }
        Update-SessionPath
        $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $winget) {
        throw ("No está disponible winget. Abra Microsoft Store, actualice 'Instalador de aplicaciones' " +
            "(App Installer), cierre esta ventana y vuelva a intentarlo.")
    }
    return $winget.Source
}

function Install-WingetPackage {
    param([string]$Id, [string]$Name, [string]$Override, [switch]$MachineScope, [switch]$UserScope)

    Write-Info "Descargando e instalando $Name (puede tardar varios minutos)..."
    $arguments = @(
        "install", "--id", $Id, "--exact", "--source", "winget", "--silent",
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"
    )
    if ($MachineScope) { $arguments += @("--scope", "machine") }
    if ($UserScope) { $arguments += @("--scope", "user") }
    if ($Override) { $arguments += @("--override", $Override) }
    # Out-Host evita que la salida de winget se mezcle con lo que devuelve quien llama.
    & (Get-Winget) @arguments | Out-Host
    # 0x8A15002B y 0x8A150061: el paquete ya estaba instalado.
    if ($LASTEXITCODE -notin @(0, -1978335189, -1978335135)) {
        throw "winget no pudo instalar $Name (código $LASTEXITCODE). Revise la conexión a Internet."
    }
    Update-SessionPath
}

function Test-IsAdministrator {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LanAddress {
    $config = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
    if ($config) {
        return [pscustomobject]@{
            Address = ($config.IPv4Address | Select-Object -First 1).IPAddress
            InterfaceIndex = $config.InterfaceIndex
            InterfaceAlias = $config.InterfaceAlias
        }
    }
    return $null
}

function Invoke-Psql {
    param([string]$User, [string]$Password, [string]$Database, [string]$Sql, [switch]$Quiet, [string]$Port = "5432")
    $previous = $env:PGPASSWORD
    $previousPreference = $ErrorActionPreference
    try {
        $env:PGPASSWORD = $Password
        # En PowerShell 5.1, redirigir stderr con Stop convierte cualquier aviso en excepción.
        $ErrorActionPreference = "Continue"
        $output = $Sql | & (Join-Path (Get-SigaPgBin) "psql.exe") -X -q -t -A -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 -p $Port -U $User -d $Database 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
        $env:PGPASSWORD = $previous
    }
    if ($code -ne 0 -and -not $Quiet) {
        throw "PostgreSQL respondió con un error: $($output -join ' ')"
    }
    return [pscustomobject]@{ Code = $code; Output = (($output | ForEach-Object { "$_" }) -join "`n").Trim() }
}
