<# :
@echo off
rem Doble clic en los dos equipos para configurar la conexion SSH con el servidor de SIGA.
rem Este archivo es a la vez un .cmd y un script de PowerShell: la parte de abajo es PowerShell.
rem Se guarda en UTF-8 SIN BOM (cmd no entiende el BOM); PowerShell lo lee como UTF-8.
setlocal
set "SSH_SETUP_FILE=%~f0"
set "SSH_SETUP_MODE=%~1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$s = [IO.File]::ReadAllText($env:SSH_SETUP_FILE, [Text.Encoding]::UTF8); & ([ScriptBlock]::Create($s))"
echo.
pause
exit /b
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ScriptFile = $env:SSH_SETUP_FILE
$ScriptDir = Split-Path -Parent $ScriptFile
$InfoFile = Join-Path $ScriptDir 'servidor-ssh.txt'
$HostAlias = 'siga-servidor'
$SshDir = Join-Path $env:USERPROFILE '.ssh'
$KeyPath = Join-Path $SshDir 'siga_servidor'
$PublicKeyName = 'siga_servidor.pub'
$WindowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Show-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Show-Ok([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Show-Note([string]$Text) { Write-Host "    $Text" -ForegroundColor Yellow }

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LanAddress {
    $addresses = @(Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        ForEach-Object { $_.IPv4Address.IPAddress })
    return $addresses
}

# ---------------------------------------------------------------- servidor --

function Install-SshServer {
    if (-not (Test-Administrator)) {
        Write-Host ''
        Write-Host 'Se necesitan permisos de administrador. Acepte el aviso de Windows.'
        Start-Process -FilePath $ScriptFile -ArgumentList 'servidor' -Verb RunAs
        Write-Host 'Continúe en la ventana nueva; puede cerrar esta.'
        return
    }

    Show-Step '1/5 Instalando el servidor SSH de Windows'
    $service = Get-Service sshd -ErrorAction SilentlyContinue
    if ($service) {
        Show-Ok 'Ya estaba instalado.'
    } else {
        $installed = $false
        try {
            $capability = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'OpenSSH.Server*' } | Select-Object -First 1
            if ($capability) {
                Write-Host '    Descargando desde Windows Update (puede tardar unos minutos)...'
                Add-WindowsCapability -Online -Name $capability.Name | Out-Null
                $installed = [bool](Get-Service sshd -ErrorAction SilentlyContinue)
            }
        } catch {
            Show-Note "Windows Update no pudo instalarlo: $($_.Exception.Message)"
        }
        if (-not $installed -and (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
            Write-Host '    Probando con winget...'
            & winget.exe install --id Microsoft.OpenSSH.Preview -e --silent --accept-source-agreements --accept-package-agreements
            $installed = [bool](Get-Service sshd -ErrorAction SilentlyContinue)
        }
        if (-not $installed) {
            throw 'No se pudo instalar el servidor SSH. Instálelo en Configuración > Sistema > Funciones opcionales > "Servidor OpenSSH" y vuelva a ejecutar este archivo.'
        }
        Show-Ok 'Instalado.'
    }

    Show-Step '2/5 Iniciando el servicio y dejándolo automático'
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    Show-Ok 'El servicio sshd está en marcha.'

    Show-Step '3/5 Usando PowerShell como consola de SSH'
    $openSshKey = 'HKLM:\SOFTWARE\OpenSSH'
    if (-not (Test-Path $openSshKey)) { New-Item -Path $openSshKey | Out-Null }
    New-ItemProperty -Path $openSshKey -Name DefaultShell -Value $WindowsPowerShell -PropertyType String -Force | Out-Null
    Show-Ok 'Listo.'

    Show-Step '4/5 Firewall y tipo de red'
    $rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
    if ($rule) {
        Enable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP'
    } else {
        New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
            -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Profile Private, Domain | Out-Null
    }
    Show-Ok 'El puerto 22 está permitido.'
    foreach ($network in @(Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' })) {
        Show-Note "La red '$($network.Name)' está marcada como pública y puede bloquear la conexión."
        $answer = Read-Host '    ¿Cambiarla a privada? Hágalo solo si es la red de su casa u oficina (S/N)'
        if ($answer -match '^[sS]') {
            Set-NetConnectionProfile -InterfaceIndex $network.InterfaceIndex -NetworkCategory Private
            Show-Ok 'Ahora es privada.'
        }
    }

    Show-Step '5/5 Llave de su computadora y datos para conectarse'
    $usbKey = Join-Path $ScriptDir $PublicKeyName
    if (Test-Path $usbKey) {
        # La opción 2 dejó la llave pública junto a este archivo (por ejemplo, en una USB).
        $publicKey = ([IO.File]::ReadAllText($usbKey)).Trim()
        if ($publicKey -notmatch '^ssh-ed25519 \S+') { throw "$usbKey no parece una llave SSH pública." }
        $result = & ([ScriptBlock]::Create((Get-AuthorizeKeyScript $publicKey)))
        if ("$result" -notmatch 'SIGA-OK') { throw 'No se pudo autorizar la llave de su computadora.' }
        Show-Ok "Llave de su computadora autorizada ($PublicKeyName)."
        $keyAuthorized = $true
    } else {
        Show-Note "No hay $PublicKeyName junto a este archivo; si el servidor no tiene contraseña,"
        Show-Note 'ejecute primero la opción 2 en su computadora y traiga la carpeta en una USB.'
        $keyAuthorized = $false
    }
    $addresses = @(Get-LanAddress)
    $user = $env:USERNAME
    if (-not (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)) {
        Show-Note 'El servicio no está escuchando en el puerto 22. Reinicie el equipo y vuelva a ejecutar este archivo.'
    }
    if ($addresses.Count -eq 0) {
        Show-Note 'No se encontró una dirección de red. Conecte el equipo a la red y vuelva a ejecutar este archivo.'
    } else {
        try {
            Set-Content -Path $InfoFile -Encoding UTF8 -Value @("ip=$($addresses[0])", "usuario=$user")
        } catch {
            # Si la carpeta es de solo lectura, basta con anotar los datos que se muestran.
        }
    }

    Write-Host ''
    Write-Host '------------------------------------------------------------'
    Write-Host " Dirección IP : $($addresses -join ', ')" -ForegroundColor Green
    Write-Host " Usuario      : $user" -ForegroundColor Green
    Write-Host '------------------------------------------------------------'
    if ($keyAuthorized) {
        Write-Host ' Vuelva a su computadora y ejecute la opción 2 para probar la conexión.'
    } else {
        Write-Host ' Anote estos datos y ejecute este mismo archivo en su computadora,'
        Write-Host ' eligiendo la opción 2.'
    }
    Write-Host ' Reserve esta IP en el router para que no cambie.'

    $diagnostics = Join-Path $ScriptDir 'diagnostico-ssh.txt'
    try {
        Write-SshDiagnostics -Path $diagnostics
        Write-Host " Si la conexión falla, lleve $([IO.Path]::GetFileName($diagnostics)) a su computadora."
    } catch {
        Show-Note "No se pudo guardar el diagnóstico: $($_.Exception.Message)"
    }
}

function Write-SshDiagnostics([string]$Path) {
    # Solo lee: cuenta, grupos, archivos de llaves con sus permisos, configuración y el
    # registro de sshd, donde Windows anota por qué rechazó cada intento.
    $ErrorActionPreference = 'Continue'
    $sshData = Join-Path $env:ProgramData 'ssh'
    $report = & {
        "Generado: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  Equipo: $env:COMPUTERNAME"
        '== Usuario que ejecutó la opción 1'
        "USERNAME=$env:USERNAME"
        whoami.exe
        whoami.exe /groups | Select-String 'S-1-5-32-544'
        '== Cuentas locales'
        Get-LocalUser | Format-Table Name, FullName, Enabled, PasswordRequired -AutoSize | Out-String -Width 200
        '== Miembros de Administradores'
        Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction SilentlyContinue | Format-Table Name, PrincipalSource -AutoSize | Out-String -Width 200
        '== administrators_authorized_keys'
        $adminKeys = Join-Path $sshData 'administrators_authorized_keys'
        if (Test-Path $adminKeys) { icacls.exe $adminKeys; (Get-Acl $adminKeys).Owner; Get-Content $adminKeys } else { 'No existe.' }
        '== authorized_keys de cada usuario'
        foreach ($file in @(Get-ChildItem 'C:\Users\*\.ssh\authorized_keys' -Force -ErrorAction SilentlyContinue)) {
            $file.FullName; icacls.exe $file.FullName; (Get-Acl $file.FullName).Owner; Get-Content $file.FullName
        }
        '== sshd_config (líneas activas)'
        Get-Content (Join-Path $sshData 'sshd_config') -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*[^#\s]' }
        '== Servicio'
        Get-Service sshd | Format-List Name, Status, StartType | Out-String
        (Get-Command sshd.exe -ErrorAction SilentlyContinue).Source
        Get-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -ErrorAction SilentlyContinue | Format-List DefaultShell | Out-String
        '== Registro de OpenSSH (más reciente primero)'
        Get-WinEvent -LogName 'OpenSSH/Operational' -MaxEvents 40 -ErrorAction SilentlyContinue |
            Format-List TimeCreated, Message | Out-String -Width 200
    } 2>&1
    Set-Content -Path $Path -Value ($report | ForEach-Object { "$_" }) -Encoding UTF8
}

# ----------------------------------------------------------------- cliente --

function Read-Value([string]$Prompt, [string]$Default) {
    $label = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    while ($true) {
        $value = (Read-Host $label).Trim()
        if (-not $value) { $value = $Default }
        if ($value) { return $value }
    }
}

function Set-SshHostEntry([string]$Address, [string]$User) {
    $configPath = Join-Path $SshDir 'config'
    $quotedUser = if ($User -match '\s') { "`"$User`"" } else { $User }
    $entry = @(
        "Host $HostAlias",
        "    HostName $Address",
        "    User $quotedUser",
        '    IdentityFile ~/.ssh/siga_servidor',
        '    IdentitiesOnly yes',
        '    StrictHostKeyChecking accept-new',
        '    ServerAliveInterval 30'
    )

    # Conserva el resto del archivo y reemplaza solo la entrada de siga-servidor.
    $kept = New-Object System.Collections.Generic.List[string]
    if (Test-Path $configPath) {
        $skipping = $false
        foreach ($line in [IO.File]::ReadAllLines($configPath)) {
            if ($line -match '^\s*(Host|Match)\s') {
                $skipping = ($line -match "^\s*Host\s+$([regex]::Escape($HostAlias))\s*$")
            }
            if (-not $skipping) { $kept.Add($line) }
        }
    }
    while ($kept.Count -gt 0 -and -not $kept[$kept.Count - 1].Trim()) { $kept.RemoveAt($kept.Count - 1) }
    if ($kept.Count -gt 0) { $kept.Add('') }
    $kept.AddRange([string[]]$entry)

    # OpenSSH no acepta el BOM en su configuración.
    [IO.File]::WriteAllText($configPath, (($kept -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding($false)))
}

function Get-AuthorizeKeyScript([string]$PublicKey) {
    # Se ejecuta en el servidor. Un usuario del grupo Administradores (S-1-5-32-544)
    # solo puede usar administrators_authorized_keys, con permisos exclusivos para
    # Administradores y SYSTEM; los SID evitan depender del idioma de Windows.
    $template = @'
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$key = '__KEY__'
function Add-AuthorizedKey([string]$Path) {
    $folder = Split-Path -Parent $Path
    if (-not (Test-Path $folder)) { New-Item -ItemType Directory -Path $folder | Out-Null }
    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content -Path $Path | Where-Object { $_.Trim() }) }
    if ($lines -notcontains $key) { Set-Content -Path $Path -Value ($lines + $key) -Encoding Ascii }
}
Add-AuthorizedKey (Join-Path $HOME '.ssh\authorized_keys')
if (@(whoami.exe /groups) -match 'S-1-5-32-544') {
    try {
        $adminKeys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
        Add-AuthorizedKey $adminKeys
        icacls.exe $adminKeys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
        'SIGA-OK-ADMIN'
    } catch {
        'SIGA-ADMIN-SIN-PERMISO'
    }
} else {
    'SIGA-OK-USUARIO'
}
'@
    return $template.Replace('__KEY__', $PublicKey.Replace("'", "''"))
}

function Connect-SshClient {
    foreach ($tool in 'ssh.exe', 'ssh-keygen.exe') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "No se encontró $tool. Instale 'Cliente OpenSSH' en Configuración > Sistema > Funciones opcionales."
        }
    }

    $defaultAddress = ''
    $defaultUser = ''
    if (Test-Path $InfoFile) {
        foreach ($line in Get-Content -Path $InfoFile -Encoding UTF8) {
            if ($line -match '^ip=(.+)$') { $defaultAddress = $Matches[1].Trim() }
            if ($line -match '^usuario=(.+)$') { $defaultUser = $Matches[1].Trim() }
        }
    }

    Show-Step '1/4 Datos del servidor (los mostró este archivo en el otro equipo)'
    $address = Read-Value '    Dirección IP del servidor' $defaultAddress
    $user = Read-Value '    Usuario de Windows del servidor' $defaultUser

    Show-Step '2/4 Llave SSH de esta computadora'
    if (-not (Test-Path $SshDir)) { New-Item -ItemType Directory -Path $SshDir | Out-Null }
    if (Test-Path $KeyPath) {
        Show-Ok "Se reutiliza $KeyPath"
    } else {
        # La llave va sin frase de paso para que Claude pueda usarla sin escribir nada.
        # '""' es el argumento vacío para -N en la línea de comandos de ssh-keygen.
        $keygen = (Get-Command ssh-keygen.exe).Source
        $arguments = "-q -t ed25519 -f `"$KeyPath`" -N `"`" -C siga-$env:COMPUTERNAME"
        $process = Start-Process -FilePath $keygen -ArgumentList $arguments -NoNewWindow -Wait -PassThru
        if ($process.ExitCode -ne 0 -or -not (Test-Path "$KeyPath.pub")) { throw 'ssh-keygen no pudo crear la llave.' }
        Show-Ok "Creada en $KeyPath"
    }
    Set-SshHostEntry -Address $address -User $user
    Show-Ok "Alias '$HostAlias' guardado en $(Join-Path $SshDir 'config')"
    $usbKey = Join-Path $ScriptDir $PublicKeyName
    $usbKeySaved = $false
    try {
        # Es la llave pública: puede viajar en una USB sin riesgo.
        Copy-Item -LiteralPath "$KeyPath.pub" -Destination $usbKey -Force
        $usbKeySaved = $true
    } catch {
        Show-Note "No se pudo copiar la llave pública junto a este archivo: $($_.Exception.Message)"
    }

    Show-Step '3/4 Probando la conexión con la llave'
    if (Test-KeyConnection) { return }
    Show-Note 'El servidor todavía no reconoce la llave de esta computadora.'

    Show-Step '4/4 Autorizando la llave en el servidor'
    $answer = Read-Host '    ¿El usuario de Windows del servidor tiene contraseña? (S/N)'
    if ($answer -notmatch '^[sS]') {
        $carry = if ($usbKeySaved) { $usbKey } else { "$KeyPath.pub" }
        Write-Host ''
        Write-Host '------------------------------------------------------------'
        Write-Host ' Windows no deja entrar por SSH con contraseña vacía, así que la'
        Write-Host ' llave se autoriza en el propio servidor:'
        Write-Host "  1. Copie a una USB este archivo y $PublicKeyName (está en"
        Write-Host "     $carry)."
        Write-Host '  2. En el servidor, ejecute el archivo desde la USB con la opción 1.'
        Write-Host '  3. Vuelva aquí y ejecute la opción 2 otra vez para probar.'
        Write-Host '------------------------------------------------------------'
        return
    }
    Write-Host '    Escriba la contraseña de Windows del servidor cuando la pida (no se verá al escribir).'
    $publicKey = ([IO.File]::ReadAllText("$KeyPath.pub")).Trim()
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes((Get-AuthorizeKeyScript $publicKey)))
    $output = & ssh.exe -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive `
        $HostAlias "powershell -NoProfile -NonInteractive -EncodedCommand $encoded"
    $pushExit = $LASTEXITCODE
    $result = ($output | Where-Object { $_ -match '^SIGA-' } | Select-Object -Last 1)
    if ($pushExit -ne 0 -or -not $result) {
        Show-Note 'No se pudo entrar al servidor. Revise que:'
        Show-Note '  - ya ejecutó este archivo en el servidor con la opción 1;'
        Show-Note '  - ambos equipos están en la misma red y la IP es correcta;'
        Show-Note '  - el usuario y la contraseña son los de Windows (no el PIN).'
        throw "ssh terminó con código $pushExit."
    }
    if ($result -eq 'SIGA-ADMIN-SIN-PERMISO') {
        throw 'El usuario es administrador, pero la sesión SSH no pudo escribir en C:\ProgramData\ssh. Ejecute la opción 1 en el servidor y vuelva a intentarlo.'
    }
    Show-Ok 'Llave autorizada.'
    if (-not (Test-KeyConnection)) {
        throw 'La llave quedó instalada, pero el servidor todavía pide contraseña. Ejecute la opción 1 en el servidor otra vez.'
    }
}

function Test-KeyConnection {
    # BatchMode impide que ssh pida contraseña: solo vale la llave. Con 'Stop',
    # PowerShell 5.1 convertiría en excepción el stderr redirigido de ssh.
    $ErrorActionPreference = 'Continue'
    $remoteName = & ssh.exe -o BatchMode=yes -o ConnectTimeout=10 $HostAlias 'hostname' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    Write-Host ''
    Write-Host '------------------------------------------------------------'
    Write-Host " Conexión lista con $(($remoteName | Select-Object -First 1))." -ForegroundColor Green
    Write-Host " Pruebe con:  ssh $HostAlias"
    Write-Host " Dígale a Claude que ya puede usar 'ssh $HostAlias'."
    Write-Host '------------------------------------------------------------'
    return $true
}

# ------------------------------------------------------------------- menú --

$mode = "$env:SSH_SETUP_MODE".ToLowerInvariant()
if (-not $mode) {
    Write-Host ''
    Write-Host 'Conexión SSH con el servidor de SIGA-MINEDUCYT' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  1. Este equipo es el SERVIDOR (donde está instalado SIGA). Hágalo primero.'
    Write-Host '  2. Este equipo es MI COMPUTADORA (desde donde me conecto).'
    Write-Host ''
    $choice = Read-Host 'Elija 1 o 2'
    $mode = switch ("$choice".Trim()) { '1' { 'servidor' } '2' { 'cliente' } default { '' } }
}

try {
    switch ($mode) {
        'servidor' { Install-SshServer }
        'cliente' { Connect-SshClient }
        default { Write-Host 'Opción no válida. Ejecute el archivo otra vez y elija 1 o 2.' -ForegroundColor Yellow }
    }
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}
