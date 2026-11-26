# Inicia SIGA-MINEDUCYT para desarrollo local (PC y teléfono en la misma red).
#
# La primera vez prepara todo lo que falte: Python, el entorno virtual, los
# paquetes, PostgreSQL, la base de desarrollo y .env.development. Las veces
# siguientes solo instala paquetes nuevos, migra y levanta runserver.
#
#   .\iniciar.ps1                 inicia (y prepara lo que falte)
#   .\iniciar.ps1 -DatosDemo      además carga o actualiza los datos de demostración
#   .\iniciar.ps1 -Configurar     vuelve a preguntar los datos de PostgreSQL
#   .\iniciar.ps1 -SoloEstaPC     solo acepta conexiones desde esta PC
#
# Solo para desarrollo: el servidor de pruebas usa instalar-servidor.cmd.
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$DatosDemo,
    [switch]$Configurar,
    [switch]$SoloEstaPC
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "deploy\windows\comun.ps1")
Set-SigaUtf8Console

$projectRoot = $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env.development"
$localDataRoot = Join-Path $env:LOCALAPPDATA "SIGA-MINEDUCYT"
$pgSuperPasswordPath = Join-Path $localDataRoot "postgres-superusuario.txt"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host $Title -ForegroundColor Cyan
}

function Test-PythonVersion {
    param([string]$Executable)
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }
    & $Executable -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    $candidates = [System.Collections.Generic.List[string]]::new()
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $candidates.Add(($resolved | Select-Object -Last 1).Trim())
        }
    }
    foreach ($name in @("python.exe", "python3.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        # El "python" de WindowsApps es un acceso a Microsoft Store, no un intérprete.
        if ($command -and $command.Source -notmatch "\\WindowsApps\\") {
            $candidates.Add($command.Source)
        }
    }
    foreach ($root in @($env:ProgramFiles, (Join-Path $env:LOCALAPPDATA "Programs\Python"))) {
        if (Test-Path -LiteralPath $root) {
            Get-ChildItem -LiteralPath $root -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { $candidates.Add((Join-Path $_.FullName "python.exe")) }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-PythonVersion $candidate) {
            return $candidate
        }
    }
    return $null
}

function Initialize-Python {
    if (Test-PythonVersion $pythonPath) {
        Write-Ok "Entorno virtual: $(& $pythonPath --version)"
    } else {
        if (Test-Path -LiteralPath $venvPath) {
            throw "El entorno .venv existe pero no funciona o su Python es anterior a 3.12. Bórrelo y vuelva a ejecutar .\iniciar.ps1."
        }
        $basePython = Find-Python
        if (-not $basePython) {
            Write-Info "No se encontró Python 3.12 o posterior."
            if (-not (Read-YesNo "¿Instalar Python 3.12 para este usuario?")) {
                throw "Instale Python 3.12 o posterior y vuelva a ejecutar .\iniciar.ps1."
            }
            Install-WingetPackage -Id "Python.Python.3.12" -Name "Python 3.12" -UserScope
            $basePython = Find-Python
            if (-not $basePython) {
                throw "Python se instaló, pero no se encontró. Cierre PowerShell, ábralo de nuevo y vuelva a ejecutar .\iniciar.ps1."
            }
        }
        Write-Info "Creando el entorno virtual con $basePython..."
        Invoke-Native $basePython @("-m", "venv", $venvPath) "No se pudo crear .venv."
        Write-Ok "Entorno virtual creado"
    }

    $requirements = Join-Path $projectRoot "requirements.txt"
    $marker = Join-Path $venvPath "requirements.sha256"
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $current = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { "" }
    if ($current -ne $hash) {
        Write-Info "Instalando los paquetes de requirements.txt..."
        Invoke-Native $pythonPath @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements) `
            "Falló la instalación de requirements.txt. Revise la conexión a Internet."
        Set-Content -LiteralPath $marker -Value $hash -Encoding ASCII
        Write-Ok "Paquetes instalados"
    } else {
        Write-Ok "Paquetes al día"
    }
}

function Test-DevDatabase {
    param([System.Collections.IDictionary]$Config)
    if (-not $Config["POSTGRES_PASSWORD"] -or -not (Get-SigaPgBin)) {
        return $false
    }
    $port = if ($Config["POSTGRES_PORT"]) { $Config["POSTGRES_PORT"] } else { "5432" }
    $probe = Invoke-Psql -User $Config["POSTGRES_USER"] -Password $Config["POSTGRES_PASSWORD"] `
        -Database $Config["POSTGRES_DB"] -Sql "SELECT 1;" -Port $port -Quiet
    return $probe.Code -eq 0
}

function Get-SuperuserPassword {
    if (Test-Path -LiteralPath $pgSuperPasswordPath) {
        $saved = (Get-Content -LiteralPath $pgSuperPasswordPath -Raw).Trim()
        if ((Invoke-Psql -User "postgres" -Password $saved -Database "postgres" -Sql "SELECT 1;" -Quiet).Code -eq 0) {
            return $saved
        }
    }
    Write-Info "Para crear la base de desarrollo se necesita la contraseña del usuario 'postgres'"
    Write-Info "(la que se eligió al instalar PostgreSQL)."
    while ($true) {
        $password = Read-Secret "Contraseña de postgres"
        if ((Invoke-Psql -User "postgres" -Password $password -Database "postgres" -Sql "SELECT 1;" -Quiet).Code -eq 0) {
            return $password
        }
        Write-Host "  PostgreSQL rechazó la contraseña." -ForegroundColor Yellow
    }
}

function Initialize-Database {
    $config = Read-SigaEnvFile -Path $envPath
    if (-not $Configurar -and (Test-DevDatabase $config)) {
        Write-Ok "PostgreSQL: base $($config["POSTGRES_DB"]) disponible"
        return $false
    }
    if (-not $Configurar -and $config["POSTGRES_PASSWORD"] -and -not (Get-SigaPgBin)) {
        # PostgreSQL en otro equipo o contenedor: no se puede comprobar con psql; Django lo hará al migrar.
        Write-Ok "PostgreSQL: se usará la configuración de .env.development"
        return $false
    }

    if ($config.Count -gt 0 -and -not $Configurar) {
        Write-Host "  No se pudo entrar a PostgreSQL con los datos de .env.development." -ForegroundColor Yellow
    }

    if (-not (Get-SigaPgBin)) {
        Write-Info "No se encontró PostgreSQL en este equipo."
        if (-not (Read-YesNo "¿Instalar PostgreSQL 16? (Windows pedirá permiso de administrador)")) {
            throw "Instale PostgreSQL o complete .env.development (vea .env.development.example)."
        }
        New-Item -ItemType Directory -Force -Path $localDataRoot | Out-Null
        $superPassword = New-RandomSecret 24
        Install-WingetPackage -Id "PostgreSQL.PostgreSQL.16" -Name "PostgreSQL 16" -Override (
            "--mode unattended --unattendedmodeui none --superpassword $superPassword " +
            "--serverport 5432 --disable-components stackbuilder")
        if (-not (Get-SigaPgBin)) {
            throw "PostgreSQL no quedó instalado."
        }
        Set-Content -LiteralPath $pgSuperPasswordPath -Value $superPassword -Encoding ASCII
        Write-Ok "PostgreSQL 16 instalado"
        Write-Info "La contraseña de 'postgres' quedó guardada en $pgSuperPasswordPath"
    }

    $service = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($service -and $service.Status -ne "Running") {
        Write-Info "Iniciando el servicio $($service.Name) (Windows pedirá permiso de administrador)..."
        Start-Process -FilePath "sc.exe" -ArgumentList @("start", $service.Name) -Verb RunAs -Wait -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-SigaTcpPort -Port 5432) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }
    if (-not (Test-SigaTcpPort -Port 5432)) {
        throw "PostgreSQL no responde en 127.0.0.1:5432. Inicie su servicio desde services.msc."
    }

    $superPassword = Get-SuperuserPassword
    $dbName = if ($config["POSTGRES_DB"]) { $config["POSTGRES_DB"] } else { "siga_mineducyt_dev" }
    $dbUser = if ($config["POSTGRES_USER"]) { $config["POSTGRES_USER"] } else { "siga_mineducyt_app" }
    if ($dbName -notmatch "^[a-z_][a-z0-9_]*$" -or $dbUser -notmatch "^[a-z_][a-z0-9_]*$") {
        throw "POSTGRES_DB y POSTGRES_USER solo pueden tener minúsculas, números y guiones bajos."
    }
    $appPassword = New-RandomSecret 24
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
    # Las pruebas crean y borran test_<base>; el usuario necesita CREATEDB.
    Invoke-Psql -User "postgres" -Password $superPassword -Database "postgres" `
        -Sql "ALTER ROLE $dbUser CREATEDB;" | Out-Null

    $config["POSTGRES_DB"] = $dbName
    $config["POSTGRES_USER"] = $dbUser
    $config["POSTGRES_PASSWORD"] = $appPassword
    $config["POSTGRES_HOST"] = "127.0.0.1"
    $config["POSTGRES_PORT"] = "5432"
    Write-SigaEnvFile -Values $config -Path $envPath -Generator "iniciar.ps1"
    Write-Ok "Base $dbName y usuario $dbUser listos; datos guardados en .env.development"
    return $true
}

function Invoke-Manage {
    param([string[]]$Arguments)
    & $pythonPath (Join-Path $projectRoot "manage.py") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falló manage.py $($Arguments -join ' ') (código $LASTEXITCODE)."
    }
}

Set-Location -LiteralPath $projectRoot
# Si quedó una configuración de otra terminal, se usa la de desarrollo.
Remove-Item Env:DJANGO_SETTINGS_MODULE -ErrorAction SilentlyContinue

try {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if ($listeners.Port -contains $Port) {
        throw "El puerto $Port ya está ocupado. Detenga el servidor anterior con Ctrl+C o use -Port con otro valor."
    }

    Write-Section "Python"
    Initialize-Python

    Write-Section "PostgreSQL"
    $newDatabase = Initialize-Database

    Write-Section "Base de datos"
    Invoke-Manage @("migrate", "--noinput")
    if ($DatosDemo -or ($newDatabase -and (Read-YesNo "¿Cargar los datos de demostración?"))) {
        Invoke-Manage @("seed_demo")
    }

    $lan = if ($SoloEstaPC) { $null } else { Get-LanAddress }
    $hosts = @()
    if ($lan) {
        $hosts += $lan.Address
        $hosts += $env:COMPUTERNAME.ToLowerInvariant()
    }
    $env:DJANGO_ALLOWED_HOSTS = $hosts -join ","
    $bind = if ($SoloEstaPC) { "127.0.0.1" } else { "0.0.0.0" }
} catch {
    Write-Host ""
    Write-Host "No se pudo iniciar: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Sistema listo" -ForegroundColor Green
Write-Host "PC:      http://127.0.0.1:$Port"
if ($lan) {
    Write-Host "Teléfono: http://$($lan.Address):$Port" -ForegroundColor Yellow
    Write-Host "Mantenga la PC y el teléfono en la misma red o hotspot."
    Write-Host "Si Windows pregunta por el firewall, permita Python en redes privadas."
} elseif (-not $SoloEstaPC) {
    Write-Warning "No se detectó una red activa. El sistema estará disponible únicamente en esta PC."
}
Write-Host "Presione Ctrl+C para detener el servidor."
Write-Host ""

& $pythonPath manage.py runserver "${bind}:$Port"
exit $LASTEXITCODE
