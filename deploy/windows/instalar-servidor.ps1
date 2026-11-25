# Instalador interactivo de SIGA-MINEDUCYT para un servidor Windows 10/11 de pruebas.
#
# Descarga e instala lo que falte (Python 3.12, PostgreSQL 16, ClamAV, IIS con
# URL Rewrite y ARR), pregunta en la consola los datos necesarios, crea la base,
# el certificado HTTPS de la red local, la cuenta de administración técnica y
# las tareas automáticas. Volver a ejecutarlo actualiza la aplicación sin
# volver a preguntar lo que ya está configurado.
#
# Uso: doble clic en instalar-servidor.cmd (pide permisos de administrador).
#   -Reconfigurar           vuelve a preguntar la dirección de acceso y el correo
#   -CertificateThumbprint  usa un certificado ya instalado en lugar del de pruebas
#   -Port                   puerto local de Waitress (predeterminado 8000)
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$Reconfigurar,
    [string]$CertificateThumbprint
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "comun.ps1")

$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonBase = Join-Path $env:ProgramFiles "Python312\python.exe"
$clamRoot = Join-Path $env:ProgramFiles "ClamAV"
$caFriendlyName = "SIGA-MINEDUCYT CA de pruebas"
$serverFriendlyName = "SIGA-MINEDUCYT servidor de pruebas"
$caExportPath = Join-Path $SigaCertRoot "SIGA-MINEDUCYT-certificado.cer"
$pgSuperPasswordPath = Join-Path $SigaSecretsRoot "postgres-superusuario.txt"
$webTaskName = "SIGA-MINEDUCYT"
$siteName = "SIGA-MINEDUCYT"
$localServiceSid = "*S-1-5-19"
$script:stepNumber = 0
$totalSteps = 12

# ---------------------------------------------------------------------------
# Consola
# ---------------------------------------------------------------------------

function Write-Step {
    param([string]$Title)
    $script:stepNumber++
    Write-Host ""
    Write-Host "[$script:stepNumber/$totalSteps] $Title" -ForegroundColor Cyan
}

function Invoke-AppPython {
    param([string[]]$Arguments, [string]$Failure)
    Push-Location -LiteralPath $SigaAppRoot
    try {
        # Out-Host muestra la salida sin mezclarla con el código que devuelve la función.
        & $SigaPython @Arguments | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($Failure -and $code -ne 0) {
        throw "$Failure (código $code)"
    }
    return $code
}

function Invoke-Manage {
    param([string[]]$Arguments)
    Invoke-AppPython -Arguments (@($SigaManage) + $Arguments) -Failure "Falló manage.py $($Arguments -join ' ')" | Out-Null
}

# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------

function Initialize-DataFolders {
    foreach ($path in @($SigaDataRoot, $SigaPrivateRoot, $SigaLogRoot, $SigaBackupRoot,
            $SigaWwwRoot, $SigaCertRoot, $SigaSecretsRoot)) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    # Raíz: solo SYSTEM y administradores. Cada subcarpeta abre lo mínimo necesario.
    Invoke-Icacls @($SigaDataRoot, "/inheritance:r", "/grant:r",
        "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", "${me}:(OI)(CI)F")
    Invoke-Icacls @($SigaPrivateRoot, "/grant", "${localServiceSid}:(OI)(CI)M")
    Invoke-Icacls @($SigaLogRoot, "/grant", "${localServiceSid}:(OI)(CI)M")
    Invoke-Icacls @($SigaWwwRoot, "/grant", "*S-1-5-32-568:(OI)(CI)RX", "*S-1-5-17:(OI)(CI)RX")
    Invoke-Icacls @($SigaCertRoot, "/grant", "*S-1-5-32-545:(OI)(CI)RX")
}

function Install-Python {
    if (-not (Test-Path -LiteralPath $pythonBase)) {
        Install-WingetPackage -Id "Python.Python.3.12" -Name "Python 3.12" -MachineScope
    }
    if (-not (Test-Path -LiteralPath $pythonBase)) {
        throw "Python 3.12 no quedó instalado en $pythonBase."
    }
    Write-Ok "Python: $(& $pythonBase --version)"
}

function Copy-Application {
    New-Item -ItemType Directory -Force -Path $SigaAppRoot | Out-Null
    if ($sourceRoot.TrimEnd("\") -ieq $SigaAppRoot.TrimEnd("\")) {
        Write-Ok "Se ejecuta desde la carpeta instalada; no se copian archivos."
    } else {
        Write-Info "Copiando la aplicación a $SigaAppRoot..."
        & robocopy.exe $sourceRoot $SigaAppRoot /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:2 `
            /XD .venv .git .github .claude .worktrees .idea .vscode staticfiles media output tmp site __pycache__ htmlcov `
            /XF .env .env.development .env.production *.pyc .coverage | Out-Null
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy no pudo copiar la aplicación (código $LASTEXITCODE)."
        }
        Write-Ok "Aplicación copiada a $SigaAppRoot"
    }
    Invoke-Icacls @($SigaAppRoot, "/grant", "${localServiceSid}:(OI)(CI)RX",
        "*S-1-5-32-568:(OI)(CI)RX", "*S-1-5-17:(OI)(CI)RX")

    if (-not (Test-Path -LiteralPath $SigaPython)) {
        Write-Info "Creando el entorno virtual..."
        Invoke-Native $pythonBase @("-m", "venv", (Join-Path $SigaAppRoot ".venv")) "No se pudo crear el entorno virtual."
    }

    $requirements = Join-Path $SigaAppRoot "requirements.txt"
    $marker = Join-Path $SigaAppRoot ".venv\requirements.sha256"
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $current = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { "" }
    if ($current -ne $hash) {
        Write-Info "Instalando los paquetes de Python..."
        Invoke-Native $SigaPython @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip") "No se pudo actualizar pip."
        Invoke-Native $SigaPython @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements) `
            "Falló la instalación de requirements.txt. Revise la conexión a Internet."
        Set-Content -LiteralPath $marker -Value $hash -Encoding ASCII
    }
    Invoke-Native $SigaPython @("-c", "import django, waitress, psycopg, axes, reportlab, openpyxl, PIL") `
        "Faltan paquetes de Python después de la instalación."
    Write-Ok "Paquetes de Python listos"
}

function Get-PostgresService {
    return Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Install-PostgreSQL {
    param([System.Collections.IDictionary]$Config)

    if (-not (Get-SigaPgBin)) {
        $superPassword = New-RandomSecret 28
        Install-WingetPackage -Id "PostgreSQL.PostgreSQL.16" -Name "PostgreSQL 16" -Override (
            "--mode unattended --unattendedmodeui none --superpassword $superPassword " +
            "--serverport 5432 --disable-components stackbuilder")
        if (-not (Get-SigaPgBin)) {
            throw "PostgreSQL no quedó instalado."
        }
        Set-Content -LiteralPath $pgSuperPasswordPath -Value $superPassword -Encoding ASCII
    }

    $service = Get-PostgresService
    if (-not $service) {
        throw "No se encontró el servicio de PostgreSQL."
    }
    if ($service.Status -ne "Running") {
        Start-Service -InputObject $service
    }
    Set-Service -Name $service.Name -StartupType Automatic
    $deadline = (Get-Date).AddMinutes(2)
    while (-not (Test-SigaTcpPort -Port 5432) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }

    $dbName = "siga_mineducyt"
    $dbUser = "siga_mineducyt_app"
    if ($Config["POSTGRES_PASSWORD"]) {
        $probe = Invoke-Psql -User $dbUser -Password $Config["POSTGRES_PASSWORD"] -Database $dbName -Sql "SELECT 1;" -Quiet
        if ($probe.Code -eq 0) {
            Write-Ok "Base de datos $dbName disponible"
            return
        }
    }

    $superPassword = if (Test-Path -LiteralPath $pgSuperPasswordPath) {
        (Get-Content -LiteralPath $pgSuperPasswordPath -Raw).Trim()
    } else {
        Write-Info "PostgreSQL ya estaba instalado. Se necesita la contraseña del usuario 'postgres'."
        Read-Secret "Contraseña de postgres"
    }
    while ((Invoke-Psql -User "postgres" -Password $superPassword -Database "postgres" -Sql "SELECT 1;" -Quiet).Code -ne 0) {
        Write-Host "  PostgreSQL rechazó la contraseña de 'postgres'." -ForegroundColor Yellow
        $superPassword = Read-Secret "Contraseña de postgres"
    }

    $appPassword = New-RandomSecret 32
    $roleSql = "DO `$`$BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '$dbUser') THEN " +
        "ALTER ROLE $dbUser LOGIN PASSWORD '$appPassword'; ELSE " +
        "CREATE ROLE $dbUser LOGIN PASSWORD '$appPassword'; END IF; END`$`$;"
    Invoke-Psql -User "postgres" -Password $superPassword -Database "postgres" -Sql $roleSql | Out-Null
    $exists = Invoke-Psql -User "postgres" -Password $superPassword -Database "postgres" `
        -Sql "SELECT 1 FROM pg_database WHERE datname = '$dbName';"
    if ($exists.Output -ne "1") {
        Invoke-Psql -User "postgres" -Password $superPassword -Database "postgres" `
            -Sql "CREATE DATABASE $dbName OWNER $dbUser ENCODING 'UTF8' TEMPLATE template0;" | Out-Null
    }
    $Config["POSTGRES_DB"] = $dbName
    $Config["POSTGRES_USER"] = $dbUser
    $Config["POSTGRES_PASSWORD"] = $appPassword
    $Config["POSTGRES_HOST"] = "127.0.0.1"
    $Config["POSTGRES_PORT"] = "5432"
    $Config["POSTGRES_SSLMODE"] = "disable"
    Write-Ok "Base de datos $dbName y usuario $dbUser listos"
}

function Get-ClamService {
    param([string]$Executable)
    return Get-CimInstance Win32_Service |
        Where-Object { $_.PathName -and $_.PathName -like "*ClamAV\$Executable*" } |
        Select-Object -First 1
}

function Install-ClamAV {
    if (-not (Test-Path -LiteralPath (Join-Path $clamRoot "clamd.exe"))) {
        Install-WingetPackage -Id "Cisco.ClamAV" -Name "ClamAV"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $clamRoot "clamd.exe"))) {
        throw "ClamAV no quedó instalado en $clamRoot."
    }

    $databasePath = Join-Path $clamRoot "database"
    New-Item -ItemType Directory -Force -Path $databasePath | Out-Null
    $configs = @{
        "clamd.conf" = @(
            "# SIGA-MINEDUCYT: escucha solo en este equipo para el análisis de archivos."
            "TCPSocket 3310"
            "TCPAddr 127.0.0.1"
            "LogFile $(Join-Path $SigaLogRoot 'clamd.log')"
            "LogFileMaxSize 10M"
            "LogTime yes"
            "StreamMaxLength 40M"
            "MaxFileSize 40M"
            "MaxScanSize 160M"
        )
        "freshclam.conf" = @(
            "# SIGA-MINEDUCYT: actualiza las firmas cada dos horas."
            "DatabaseMirror database.clamav.net"
            "Checks 12"
            "UpdateLogFile $(Join-Path $SigaLogRoot 'freshclam.log')"
            "LogFileMaxSize 10M"
            "LogTime yes"
        )
    }
    foreach ($name in $configs.Keys) {
        $path = Join-Path $clamRoot $name
        if ((Test-Path -LiteralPath $path) -and
            -not (Select-String -LiteralPath $path -SimpleMatch "SIGA-MINEDUCYT" -Quiet)) {
            Copy-Item -LiteralPath $path -Destination "$path.antes-de-siga" -Force
        }
        [System.IO.File]::WriteAllLines($path, [string[]]$configs[$name], (New-Object System.Text.UTF8Encoding -ArgumentList $false))
    }

    $hasSignatures = Get-ChildItem -LiteralPath $databasePath -Include "*.cvd", "*.cld" -File -Recurse -ErrorAction SilentlyContinue
    if (-not $hasSignatures) {
        Write-Info "Descargando las firmas del antivirus (unos 300 MB, puede tardar)..."
        Invoke-Native (Join-Path $clamRoot "freshclam.exe") @() "freshclam no pudo descargar las firmas."
    }

    foreach ($executable in @("clamd.exe", "freshclam.exe")) {
        $service = Get-ClamService $executable
        if (-not $service) {
            Invoke-Native (Join-Path $clamRoot $executable) @("--install-service") "No se pudo registrar el servicio de $executable."
            $service = Get-ClamService $executable
        }
        if (-not $service) {
            throw "No se encontró el servicio de $executable después de registrarlo."
        }
        Set-Service -Name $service.Name -StartupType Automatic
        & sc.exe failure $service.Name reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
        if ((Get-Service -Name $service.Name).Status -ne "Running") {
            Start-Service -Name $service.Name
        }
    }

    Write-Info "Esperando a que ClamAV cargue las firmas..."
    $deadline = (Get-Date).AddMinutes(5)
    while (-not (Test-SigaClamAV) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
    }
    if (-not (Test-SigaClamAV)) {
        throw "ClamAV no respondió en 127.0.0.1:3310. Revise $(Join-Path $SigaLogRoot 'clamd.log')."
    }
    Write-Ok "ClamAV responde en 127.0.0.1:3310"
}

function Set-AccessAddress {
    param([System.Collections.IDictionary]$Config)

    $lan = Get-LanAddress
    $detected = if ($lan) { $lan.Address } else { "" }
    $currentHost = if ($Config["PUBLIC_BASE_URL"]) { ([Uri]$Config["PUBLIC_BASE_URL"]).Host } else { "" }
    $hostName = $env:COMPUTERNAME.ToLowerInvariant()

    $ask = $Reconfigurar -or -not $currentHost
    if (-not $ask -and $detected -and $currentHost -match "^\d+\.\d+\.\d+\.\d+$" -and $currentHost -ne $detected) {
        Write-Host "  La dirección de este equipo cambió de $currentHost a $detected." -ForegroundColor Yellow
        $ask = Read-YesNo "¿Actualizar SIGA para usar $detected?"
    }

    if ($ask) {
        Write-Info "Dirección con la que los demás equipos abrirán SIGA."
        Write-Info "Puede ser la IP ($detected) o el nombre del equipo ($hostName)."
        $address = (Read-Value "Dirección de acceso" -Default $(if ($detected) { $detected } else { $hostName })).ToLowerInvariant()
        if ([Uri]::CheckHostName($address) -notin @([UriHostNameType]::IPv4, [UriHostNameType]::Dns)) {
            throw "La dirección '$address' no es una IP ni un nombre de equipo válido."
        }
    } else {
        $address = $currentHost
    }

    $hosts = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @($address, $detected, $hostName, "localhost", "127.0.0.1")) {
        if ($candidate -and -not $hosts.Contains($candidate)) {
            $hosts.Add($candidate)
        }
    }
    $Config["DJANGO_ALLOWED_HOSTS"] = $hosts -join ","
    $Config["DJANGO_CSRF_TRUSTED_ORIGINS"] = ($hosts | ForEach-Object { "https://$_" }) -join ","
    $Config["PUBLIC_BASE_URL"] = "https://$address"
    Write-Ok "SIGA se abrirá en https://$address"

    if ($lan) {
        $netProfile = Get-NetConnectionProfile -InterfaceIndex $lan.InterfaceIndex -ErrorAction SilentlyContinue
        if ($netProfile -and $netProfile.NetworkCategory -eq "Public") {
            Write-Host "  La red '$($netProfile.Name)' está marcada como pública; Windows bloqueará las conexiones de otros equipos." -ForegroundColor Yellow
            if (Read-YesNo "¿Marcarla como red privada?") {
                Set-NetConnectionProfile -InterfaceIndex $lan.InterfaceIndex -NetworkCategory Private
                Write-Ok "Red '$($netProfile.Name)' marcada como privada"
            }
        }
    }
    return $hosts
}

function Set-EmailSettings {
    param([System.Collections.IDictionary]$Config)

    if ($Config["EMAIL_HOST"] -and -not $Reconfigurar) {
        Write-Ok "Correo configurado: $($Config["EMAIL_HOST"]) ($($Config["DEFAULT_FROM_EMAIL"]))"
        return
    }
    Write-Info "SIGA envía invitaciones y avisos por correo. Para Gmail use smtp.gmail.com,"
    Write-Info "puerto 587 y una contraseña de aplicación (myaccount.google.com/apppasswords)."
    while ($true) {
        $smtpHost = Read-Value "Servidor SMTP" -Default $(if ($Config["EMAIL_HOST"]) { $Config["EMAIL_HOST"] } else { "smtp.gmail.com" })
        $smtpPort = Read-Value "Puerto" -Default $(if ($Config["EMAIL_PORT"]) { $Config["EMAIL_PORT"] } else { "587" })
        $smtpUser = Read-Value "Usuario (correo)" -Default $Config["EMAIL_HOST_USER"] -AllowEmpty
        $smtpPassword = if ($smtpUser) { Read-Secret "Contraseña del correo" } else { "" }
        $fromDefault = if ($Config["DEFAULT_FROM_EMAIL"]) { $Config["DEFAULT_FROM_EMAIL"] } else { $smtpUser }
        $fromEmail = Read-Value "Remitente que verán los usuarios" -Default $fromDefault
        $useSsl = $smtpPort -eq "465"

        $env:EMAIL_HOST = $smtpHost
        $env:EMAIL_PORT = $smtpPort
        $env:EMAIL_HOST_USER = $smtpUser
        $env:EMAIL_HOST_PASSWORD = $smtpPassword
        $env:EMAIL_USE_SSL = if ($useSsl) { "true" } else { "false" }
        Write-Info "Probando la conexión..."
        $code = Invoke-AppPython -Arguments @((Join-Path $SigaAppRoot "deploy\windows\probar_smtp.py"))
        Remove-Item Env:EMAIL_HOST_PASSWORD -ErrorAction SilentlyContinue
        if ($code -eq 0) {
            break
        }
        if (-not (Read-YesNo "¿Volver a escribir los datos del correo?")) {
            throw "Sin un correo que funcione, SIGA no puede iniciar (deployment_preflight lo exige)."
        }
    }
    $Config["EMAIL_HOST"] = $smtpHost
    $Config["EMAIL_PORT"] = $smtpPort
    $Config["EMAIL_HOST_USER"] = $smtpUser
    $Config["EMAIL_HOST_PASSWORD"] = $smtpPassword
    $Config["EMAIL_USE_TLS"] = if ($useSsl) { "false" } else { "true" }
    $Config["EMAIL_USE_SSL"] = if ($useSsl) { "true" } else { "false" }
    $Config["DEFAULT_FROM_EMAIL"] = $fromEmail
    Write-Ok "Correo configurado"
}

function Save-Configuration {
    param([System.Collections.IDictionary]$Config)

    if (-not $Config["DJANGO_SECRET_KEY"]) {
        $Config["DJANGO_SECRET_KEY"] = New-RandomSecret 64
    }
    $defaults = [ordered]@{
        # Servidor de pruebas: sin HSTS para que el certificado local no bloquee a nadie.
        DJANGO_HSTS_SECONDS = "0"
        FILE_SCAN_REQUIRED = "true"
        FILE_MAX_UPLOAD_MB = "20"
        PRIVATE_MEDIA_ROOT = $SigaPrivateRoot
        CLAMAV_HOST = "127.0.0.1"
        CLAMAV_PORT = "3310"
    }
    foreach ($name in $defaults.Keys) {
        if (-not $Config.Contains($name) -or -not $Config[$name]) {
            $Config[$name] = $defaults[$name]
        }
    }
    Write-SigaEnvFile -Values $Config
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Invoke-Icacls @($SigaEnvPath, "/inheritance:r", "/grant:r",
        "*S-1-5-18:F", "*S-1-5-32-544:F", "${me}:F", "${localServiceSid}:R")
    Invoke-Icacls @($SigaSecretsRoot, "/inheritance:r", "/grant:r",
        "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F")
    Write-Ok "Configuración guardada en $SigaEnvPath"
}

function Stop-WebTask {
    $task = Get-ScheduledTask -TaskName $webTaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Write-Info "Deteniendo SIGA para actualizarlo..."
        Stop-ScheduledTask -TaskName $webTaskName
    }
    # Detener la tarea no siempre termina el proceso hijo de Python.
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*waitress*" -and $_.ExecutablePath -like "$SigaAppRoot*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $deadline = (Get-Date).AddSeconds(20)
    while ((Test-SigaTcpPort -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
    }
    if (Test-SigaTcpPort -Port $Port) {
        throw "El puerto local $Port sigue ocupado por otro programa. Ciérrelo o use -Port con otro valor."
    }
}

function Initialize-Django {
    param([bool]$IsUpdate)

    Import-SigaEnvironment | Out-Null
    Invoke-Manage @("check", "--deploy", "--fail-level", "ERROR")
    if ($IsUpdate) {
        Write-Info "Respaldando la base de datos antes de migrar..."
        $backup = New-SigaDatabaseBackup -Prefix "antes-de-actualizar"
        Write-Ok "Respaldo verificado: $backup"
    }
    Invoke-Manage @("migrate", "--noinput")
    Invoke-Manage @("collectstatic", "--noinput", "--verbosity", "0")
    Invoke-Icacls @((Join-Path $SigaAppRoot "staticfiles"), "/grant",
        "*S-1-5-32-568:(OI)(CI)RX", "*S-1-5-17:(OI)(CI)RX", "/T", "/C")
    Write-Ok "Migraciones y archivos estáticos listos"

    $adminScript = Join-Path $SigaAppRoot "deploy\windows\crear_admin.py"
    if ((Invoke-AppPython -Arguments @($adminScript, "existe")) -eq 0) {
        Write-Ok "Ya existe una cuenta de administración técnica"
        return
    }
    Write-Info "Cree la cuenta de administración técnica (desde ella se crean las demás)."
    while ($true) {
        $env:SIGA_ADMIN_USERNAME = Read-Value "Usuario"
        $env:SIGA_ADMIN_FIRST_NAME = Read-Value "Nombres" -AllowEmpty
        $env:SIGA_ADMIN_LAST_NAME = Read-Value "Apellidos" -AllowEmpty
        $env:SIGA_ADMIN_EMAIL = Read-Value "Correo" -AllowEmpty
        $env:SIGA_ADMIN_PASSWORD = Read-Secret "Contraseña" -Confirm
        $code = Invoke-AppPython -Arguments @($adminScript, "crear")
        Remove-Item Env:SIGA_ADMIN_PASSWORD -ErrorAction SilentlyContinue
        if ($code -eq 0) {
            $script:adminUser = $env:SIGA_ADMIN_USERNAME
            break
        }
        Write-Host "  Corrija los datos indicados e inténtelo de nuevo." -ForegroundColor Yellow
    }
}

function Install-Iis {
    $features = @("IIS-WebServerRole", "IIS-WebServer", "IIS-CommonHttpFeatures", "IIS-StaticContent",
        "IIS-DefaultDocument", "IIS-HttpErrors", "IIS-HttpLogging", "IIS-RequestFiltering",
        "IIS-HttpCompressionStatic", "IIS-ManagementConsole", "IIS-ManagementScriptingTools")
    $restart = $false
    foreach ($feature in $features) {
        $state = Get-WindowsOptionalFeature -Online -FeatureName $feature
        if ($state.State -ne "Enabled") {
            Write-Info "Habilitando $feature..."
            $result = Enable-WindowsOptionalFeature -Online -FeatureName $feature -All -NoRestart
            $restart = $restart -or $result.RestartNeeded
        }
    }
    if ($restart) {
        throw "Windows debe reiniciarse para terminar de habilitar IIS. Reinicie y vuelva a ejecutar instalar-servidor.cmd."
    }
    Import-Module WebAdministration

    $appcmd = Join-Path $env:WINDIR "System32\inetsrv\appcmd.exe"
    $modules = & $appcmd list modules /text:name
    if ($modules -notcontains "RewriteModule") {
        Install-WingetPackage -Id "Microsoft.IIS.URLRewrite" -Name "IIS URL Rewrite"
    }
    $modules = & $appcmd list modules /text:name
    if ($modules -notcontains "ApplicationRequestRouting") {
        Install-WingetPackage -Id "Microsoft.IIS.ApplicationRequestRouting" -Name "IIS Application Request Routing"
    }
    $modules = & $appcmd list modules /text:name
    if ($modules -notcontains "RewriteModule" -or $modules -notcontains "ApplicationRequestRouting") {
        throw "IIS no cargó URL Rewrite y ARR. Reinicie Windows y vuelva a ejecutar instalar-servidor.cmd."
    }

    $variables = (& $appcmd list config -section:system.webServer/rewrite/allowedServerVariables) -join "`n"
    if ($variables -notmatch "HTTP_X_FORWARDED_PROTO") {
        Invoke-Native $appcmd @("set", "config", "-section:system.webServer/rewrite/allowedServerVariables",
            "/+[name='HTTP_X_FORWARDED_PROTO']", "/commit:apphost") "No se pudo permitir X-Forwarded-Proto en IIS."
    }
    # ARR agrega X-Forwarded-For con la IP real (sin puerto) al final de la cabecera.
    Invoke-Native $appcmd @("set", "config", "-section:system.webServer/proxy", "/enabled:True",
        "/preserveHostHeader:True", "/reverseRewriteHostInResponseHeaders:False",
        "/xForwardedForHeaderName:X-Forwarded-For", "/includePortInXForwardedFor:False",
        "/timeout:00:03:00", "/commit:apphost") "No se pudo configurar el proxy de IIS."
    Write-Ok "IIS con URL Rewrite y ARR listo"
}

function New-TestCertificate {
    param([string[]]$Names)

    $ca = Get-ChildItem Cert:\LocalMachine\My |
        Where-Object { $_.FriendlyName -eq $caFriendlyName -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
        Sort-Object NotAfter -Descending | Select-Object -First 1
    if (-not $ca) {
        Write-Info "Creando la autoridad de certificación local de pruebas..."
        $ca = New-SelfSignedCertificate -Subject "CN=SIGA-MINEDUCYT CA de pruebas ($env:COMPUTERNAME)" `
            -FriendlyName $caFriendlyName -CertStoreLocation Cert:\LocalMachine\My `
            -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable `
            -KeyUsage CertSign, CRLSign, DigitalSignature -NotAfter (Get-Date).AddYears(5) `
            -TextExtension @("2.5.29.19={critical}{text}ca=1&pathlength=0")
    }
    $root = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "LocalMachine")
    $root.Open("ReadWrite")
    try {
        if (-not ($root.Certificates | Where-Object { $_.Thumbprint -eq $ca.Thumbprint })) {
            $root.Add([System.Security.Cryptography.X509Certificates.X509Certificate2]::new($ca.RawData))
        }
    } finally {
        $root.Close()
    }
    [System.IO.File]::WriteAllBytes($caExportPath, $ca.RawData)
    $publicDesktop = Join-Path $env:PUBLIC "Desktop"
    if (Test-Path -LiteralPath $publicDesktop) {
        Copy-Item -LiteralPath $caExportPath -Destination $publicDesktop -Force
    }

    $sanParts = foreach ($name in $Names) {
        if ([Uri]::CheckHostName($name) -eq [UriHostNameType]::IPv4) { "IPAddress=$name" } else { "DNS=$name" }
    }
    $san = $sanParts -join "&"
    $existing = Get-ChildItem Cert:\LocalMachine\My |
        Where-Object { $_.FriendlyName -eq $serverFriendlyName -and $_.HasPrivateKey -and
            $_.NotAfter -gt (Get-Date).AddDays(30) -and $_.Issuer -eq $ca.Subject } |
        Sort-Object NotAfter -Descending | Select-Object -First 1
    if ($existing) {
        $sanText = ($existing.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }).Format($false)
        $covered = $true
        foreach ($name in $Names) {
            if ($sanText -notmatch "(DNS Name|IP Address)=$([regex]::Escape($name))(,|$)") {
                $covered = $false
            }
        }
        if ($covered) {
            return $existing.Thumbprint
        }
    }
    Write-Info "Creando el certificado HTTPS para $($Names -join ', ')..."
    $server = New-SelfSignedCertificate -Subject "CN=$($Names[0])" -FriendlyName $serverFriendlyName `
        -Signer $ca -CertStoreLocation Cert:\LocalMachine\My -KeyAlgorithm RSA -KeyLength 2048 `
        -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddDays(730) `
        -TextExtension @("2.5.29.17={text}$san", "2.5.29.37={text}1.3.6.1.5.5.7.3.1")
    return $server.Thumbprint
}

function Set-IisSite {
    param([string]$Thumbprint)

    Import-Module WebAdministration
    $defaultSite = Get-Website -Name "Default Web Site" -ErrorAction SilentlyContinue
    if ($defaultSite) {
        Write-Info "Quitando el sitio de ejemplo de IIS (Default Web Site)..."
        Remove-Website -Name "Default Web Site"
    }

    $poolPath = "IIS:\AppPools\$siteName"
    if (-not (Test-Path $poolPath)) {
        New-WebAppPool -Name $siteName | Out-Null
    }
    Set-ItemProperty $poolPath -Name managedRuntimeVersion -Value ""

    if (-not (Get-Website -Name $siteName -ErrorAction SilentlyContinue)) {
        New-Website -Name $siteName -PhysicalPath $SigaWwwRoot -Port 80 -IPAddress "*" -ApplicationPool $siteName | Out-Null
    } else {
        Set-ItemProperty "IIS:\Sites\$siteName" -Name physicalPath -Value $SigaWwwRoot
        Set-ItemProperty "IIS:\Sites\$siteName" -Name applicationPool -Value $siteName
    }
    if (-not (Get-WebBinding -Name $siteName -Protocol http -Port 80)) {
        New-WebBinding -Name $siteName -Protocol http -Port 80 -IPAddress "*" | Out-Null
    }
    if (-not (Get-WebBinding -Name $siteName -Protocol https -Port 443)) {
        New-WebBinding -Name $siteName -Protocol https -Port 443 -IPAddress "*" | Out-Null
    }
    # Reemplaza el certificado de 0.0.0.0:443 aunque ya hubiera uno (reinstalaciones).
    & netsh.exe http delete sslcert ipport=0.0.0.0:443 | Out-Null
    (Get-WebBinding -Name $siteName -Protocol https -Port 443).AddSslCertificate($Thumbprint, "My")

    $staticRoot = Join-Path $SigaAppRoot "staticfiles"
    if (-not (Get-WebVirtualDirectory -Site $siteName -Name "static")) {
        New-WebVirtualDirectory -Site $siteName -Name "static" -PhysicalPath $staticRoot | Out-Null
    } else {
        Set-ItemProperty "IIS:\Sites\$siteName\static" -Name physicalPath -Value $staticRoot
    }

    $webConfig = @'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <!-- Generado por instalar-servidor.ps1 de SIGA-MINEDUCYT. -->
  <system.webServer>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="104857600" />
      </requestFiltering>
    </security>
    <rewrite>
      <rules>
        <rule name="SIGA HTTPS" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="^OFF$" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
        <rule name="SIGA proxy" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{REQUEST_URI}" pattern="^/static/" negate="true" />
          </conditions>
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
          <action type="Rewrite" url="http://127.0.0.1:__PORT__/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
'@
    [System.IO.File]::WriteAllText((Join-Path $SigaWwwRoot "web.config"), $webConfig.Replace("__PORT__", [string]$Port),
        (New-Object System.Text.UTF8Encoding -ArgumentList $false))

    if ((Get-Website -Name $siteName).State -ne "Started") {
        Start-Website -Name $siteName
    }
    Write-Ok "Sitio IIS en los puertos 80 y 443"
}

function Set-Firewall {
    $ruleName = "SIGA-MINEDUCYT (HTTP y HTTPS)"
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort 80, 443 -Profile Domain, Private -RemoteAddress LocalSubnet | Out-Null
    Write-Ok "Firewall: puertos 80 y 443 abiertos solo para la red local"
}

function Register-Tasks {
    $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    $runner = Join-Path $SigaAppRoot "deploy\windows\servicio.ps1"
    $localService = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\LOCAL SERVICE" -LogonType ServiceAccount -RunLevel Limited
    $system = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    function New-Action([string]$Mode) {
        New-ScheduledTaskAction -Execute $powershell -WorkingDirectory $SigaAppRoot `
            -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Mode $Mode -Port $Port"
    }
    function New-Settings([TimeSpan]$Limit) {
        New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit $Limit `
            -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    }

    $tasks = @(
        @{ Name = $webTaskName; Mode = "web"; Principal = $localService; Limit = [TimeSpan]::Zero
            Trigger = (New-ScheduledTaskTrigger -AtStartup); Description = "SIGA-MINEDUCYT: Waitress detrás de IIS." },
        @{ Name = "SIGA-MINEDUCYT-VENCIMIENTOS"; Mode = "overdue"; Principal = $localService; Limit = (New-TimeSpan -Hours 2)
            Trigger = (New-ScheduledTaskTrigger -Daily -At "02:00"); Description = "SIGA-MINEDUCYT: recomendaciones vencidas." },
        @{ Name = "SIGA-MINEDUCYT-VERIFICAR-ARCHIVOS"; Mode = "verify-storage"; Principal = $localService; Limit = (New-TimeSpan -Hours 6)
            Trigger = (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"); Description = "SIGA-MINEDUCYT: verificación de documentos privados." },
        @{ Name = "SIGA-MINEDUCYT-RESPALDO"; Mode = "backup"; Principal = $system; Limit = (New-TimeSpan -Hours 2)
            Trigger = (New-ScheduledTaskTrigger -Daily -At "01:30"); Description = "SIGA-MINEDUCYT: respaldo diario de PostgreSQL (14 días)." }
    )
    foreach ($task in $tasks) {
        Register-ScheduledTask -TaskName $task.Name -Action (New-Action $task.Mode) -Trigger $task.Trigger `
            -Principal $task.Principal -Settings (New-Settings $task.Limit) -Description $task.Description -Force | Out-Null
    }
    Start-ScheduledTask -TaskName $webTaskName

    Write-Info "Iniciando SIGA..."
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-SigaTcpPort -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
    }
    if (-not (Test-SigaTcpPort -Port $Port)) {
        throw "SIGA no respondió en 127.0.0.1:$Port. Revise $(Join-Path $SigaLogRoot 'web.log')."
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if ($CertificateThumbprint) {
        # Un certificado propio no incluye 127.0.0.1; aquí solo se comprueba que IIS responda.
        [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
    $request = [System.Net.HttpWebRequest]::Create("https://127.0.0.1/")
    $request.AllowAutoRedirect = $false
    $request.Timeout = 30000
    try {
        $response = $request.GetResponse()
        $status = [int]$response.StatusCode
        $response.Close()
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
        } else {
            throw "IIS no respondió por HTTPS: $($_.Exception.Message)"
        }
    }
    if ($status -ge 500) {
        throw "SIGA respondió con error $status. Revise $(Join-Path $SigaLogRoot 'web.log')."
    }
    Write-Ok "SIGA responde por HTTPS (código $status)"
}

function Set-PowerSettings {
    if (-not (Read-YesNo "¿Evitar que el equipo se suspenda mientras esté conectado a la corriente?")) {
        return
    }
    & powercfg.exe /change standby-timeout-ac 0
    & powercfg.exe /change hibernate-timeout-ac 0
    # Cerrar la tapa conectado a la corriente: no hacer nada.
    & powercfg.exe /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    & powercfg.exe /setactive SCHEME_CURRENT
    Write-Ok "El equipo no se suspenderá conectado a la corriente (ni al cerrar la tapa)"
}

# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------

if ($PSVersionTable.PSEdition -ne "Desktop") {
    throw "Ejecute este instalador con Windows PowerShell 5.1 (instalar-servidor.cmd lo hace por usted)."
}
if (-not [Environment]::Is64BitProcess) {
    throw "Ejecute este instalador desde PowerShell de 64 bits."
}
if (-not (Test-IsAdministrator)) {
    throw "Ejecute instalar-servidor.cmd: necesita permisos de administrador."
}

Initialize-DataFolders
$transcript = Join-Path $SigaLogRoot "instalacion-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
Start-Transcript -LiteralPath $transcript | Out-Null
$script:adminUser = $null

try {
    Write-Host ""
    Write-Host "SIGA-MINEDUCYT: instalación del servidor de pruebas" -ForegroundColor White
    Write-Host "Mantenga el equipo conectado a Internet y a la corriente durante la instalación."

    $config = Read-SigaEnvFile
    $isUpdate = $config.Count -gt 0

    Write-Step "Herramientas de instalación"
    Get-Winget | Out-Null
    Write-Ok "winget disponible"

    Write-Step "Python 3.12"
    Install-Python

    Write-Step "Aplicación y paquetes de Python"
    Stop-WebTask
    Copy-Application

    Write-Step "PostgreSQL"
    Install-PostgreSQL -Config $config

    Write-Step "Antivirus ClamAV"
    Install-ClamAV

    Write-Step "Dirección de acceso en la red"
    $hostNames = Set-AccessAddress -Config $config

    Write-Step "Correo saliente"
    Set-EmailSettings -Config $config
    Save-Configuration -Config $config

    Write-Step "Base de datos y cuenta de administración"
    Initialize-Django -IsUpdate $isUpdate

    Write-Step "IIS"
    Install-Iis

    Write-Step "Certificado HTTPS y sitio web"
    $thumbprint = if ($CertificateThumbprint) { $CertificateThumbprint -replace "\s", "" } else { New-TestCertificate -Names $hostNames }
    Set-IisSite -Thumbprint $thumbprint
    Set-Firewall

    Write-Step "Verificación final y tareas automáticas"
    Invoke-Manage @("deployment_preflight")
    Register-Tasks

    Write-Step "Energía"
    Set-PowerSettings

    $url = Read-SigaEnvFile
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " SIGA-MINEDUCYT está listo" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " Dirección:      $($url["PUBLIC_BASE_URL"])"
    if ($script:adminUser) {
        Write-Host " Administración: usuario '$script:adminUser'"
    }
    Write-Host ""
    Write-Host " Para que los navegadores no muestren advertencias, instale este"
    Write-Host " certificado en cada equipo que vaya a usar SIGA:"
    Write-Host "   $caExportPath"
    Write-Host "   (también quedó una copia en el escritorio público)"
    Write-Host "   Windows: doble clic > Instalar certificado > Equipo local >"
    Write-Host "            Entidades de certificación raíz de confianza."
    Write-Host "   Android: Ajustes > Seguridad > Cifrado y credenciales >"
    Write-Host "            Instalar un certificado > Certificado de CA."
    Write-Host ""
    Write-Host " Registros:      $SigaLogRoot"
    Write-Host " Respaldos:      $SigaBackupRoot (diarios, 14 días)"
    Write-Host " Actualizar:     copie la nueva versión y ejecute de nuevo instalar-servidor.cmd"
    Write-Host " Comandos:       & `"$(Join-Path $SigaAppRoot 'deploy\windows\siga.ps1')`" <comando>"
    Write-Host ""
    Write-Host " Si la IP del equipo cambia, ejecute de nuevo el instalador para actualizarla."
    Write-Host " Lo ideal es reservar la IP de este equipo en el router."
} catch {
    Write-Host ""
    Write-Host "La instalación se detuvo: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Registro completo: $transcript" -ForegroundColor Yellow
    Write-Host "Puede corregir el problema y volver a ejecutar instalar-servidor.cmd; los pasos ya hechos se conservan."
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
