# PowerShell Installer for Media Manager CLI on Windows
[CmdletBinding()]
param(
    [switch]$AllUsers,
    [switch]$CurrentUser
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Instalador de Media Manager CLI (Windows)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$publicDir = if ($env:PUBLIC) { $env:PUBLIC } else { "C:\Users\Public" }

if ($AllUsers) {
    $installAllUsers = $true
} elseif ($CurrentUser) {
    $installAllUsers = $false
} else {
    Write-Host "Selecciona el modo de instalacion:" -ForegroundColor Yellow
    Write-Host "  [1] Solo para el usuario actual ($HOME)"
    Write-Host "  [2] Para todos los usuarios ($publicDir)"
    $choice = Read-Host "Elige una opcion (1/2) [Por defecto: 2]"
    if ($choice.Trim() -eq "1") {
        $installAllUsers = $false
    } else {
        $installAllUsers = $true
    }
    Write-Host ""
}

$BASE_DIR = if ($installAllUsers) { $publicDir } else { $HOME }
$modeLabel = if ($installAllUsers) { "Todos los usuarios ($BASE_DIR)" } else { "Usuario actual ($BASE_DIR)" }
Write-Host "Modo seleccionado: $modeLabel" -ForegroundColor Cyan
Write-Host ""

$localBin = Join-Path $BASE_DIR ".local\bin"
New-Item -ItemType Directory -Force -Path $localBin | Out-Null

# 1. Verificar e instalar aria2c
Write-Host "[1/6] Verificando dependencia del sistema: aria2c..." -ForegroundColor Yellow

$aria2Found = $null
$sharedAria2 = Join-Path $localBin "aria2c.exe"
if (Test-Path $sharedAria2) {
    $aria2Found = $sharedAria2
} elseif (Get-Command aria2c -ErrorAction SilentlyContinue) {
    $aria2Found = (Get-Command aria2c).Source
} else {
    # Buscar en paquetes de WinGet
    $wingetPkg = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $wingetPkg) {
        $foundExe = Get-ChildItem -Path $wingetPkg -Filter "aria2c.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($foundExe) {
            $aria2Found = $foundExe.FullName
        }
    }
}

if (-not $aria2Found) {
    Write-Host "aria2c no esta en el PATH. Intentando instalar mediante WinGet..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install aria2.aria2 --accept-source-agreements --accept-package-agreements
            Write-Host "[OK] aria2c instalado con exito mediante WinGet." -ForegroundColor Green
        } catch {
            Write-Warning "Fallo la instalacion con winget: $_"
        }
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        try {
            choco install aria2 -y
            Write-Host "[OK] aria2c instalado con exito mediante Chocolatey." -ForegroundColor Green
        } catch {
            Write-Warning "Fallo la instalacion con choco: $_"
        }
    } else {
        Write-Warning "No se encontro WinGet ni Chocolatey. Por favor instala aria2 manualmente desde https://aria2.github.io/"
    }

    # Recargar PATH desde el registro
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPathEnv = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPathEnv"

    if (Get-Command aria2c -ErrorAction SilentlyContinue) {
        $aria2Found = (Get-Command aria2c).Source
    } else {
        $wingetPkg = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
        if (Test-Path $wingetPkg) {
            $foundExe = Get-ChildItem -Path $wingetPkg -Filter "aria2c.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($foundExe) {
                $aria2Found = $foundExe.FullName
            }
        }
    }
} else {
    Write-Host "[OK] aria2c encontrado: $aria2Found" -ForegroundColor Green
}

# Si es instalacion para todos los usuarios, copiar aria2c.exe a C:\Users\Public\.local\bin
if ($installAllUsers -and $aria2Found -and (Test-Path $aria2Found)) {
    if ($aria2Found -ne $sharedAria2) {
        # Detener aria2c temporalmente si esta en uso desde esa ruta
        Stop-Process -Name "aria2c" -Force -ErrorAction SilentlyContinue
        Copy-Item -Path $aria2Found -Destination $sharedAria2 -Force
        Write-Host "[OK] aria2c copiado a carpeta compartida: '$sharedAria2'" -ForegroundColor Green
    }
}

# 2. Verificar Python
Write-Host "[2/6] Verificando entorno de Python..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    Write-Error "Error: Python no esta instalado o no se encuentra en el PATH. Instala Python 3.8+ antes de continuar."
    exit 1
}
$pythonExe = $pythonCmd.Source
$pyVersion = & $pythonExe --version 2>&1
Write-Host "[OK] Usando $pyVersion ($pythonExe)" -ForegroundColor Green

$pythonForVenv = $pythonExe

# Si se instala para todos los usuarios y Python esta dentro de una carpeta privada de usuario (ej. AppData\Local),
# copiar el runtime base de Python a C:\Users\Public\.local\share\media_manager\python para que otros usuarios puedan ejecutar el venv.
if ($installAllUsers) {
    $pyBasePrefix = (& $pythonExe -c "import sys; print(sys.base_prefix)").Trim()
    if ($pyBasePrefix -like "$HOME*" -or ($pyBasePrefix -like "C:\Users\*" -and $pyBasePrefix -notlike "$publicDir*")) {
        $sharedPyDir = Join-Path $BASE_DIR ".local\share\media_manager\python"
        $sharedPyExe = Join-Path $sharedPyDir "python.exe"
        Write-Host "Copiando runtime base de Python a '$sharedPyDir' para acceso multiusuario..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Force -Path $sharedPyDir | Out-Null

        # Copiar ejecutables y DLLs principales de la raiz de Python
        Get-ChildItem -Path $pyBasePrefix -File | Copy-Item -Destination $sharedPyDir -Force

        # Copiar DLLs y Lib (excluyendo site-packages y test para mantenerlo liviano)
        $null = robocopy (Join-Path $pyBasePrefix "DLLs") (Join-Path $sharedPyDir "DLLs") /E /NFL /NDL /NJH /NJS /NC /NS /NP
        $null = robocopy (Join-Path $pyBasePrefix "Lib") (Join-Path $sharedPyDir "Lib") /E /XD "site-packages" "test" "__pycache__" /NFL /NDL /NJH /NJS /NC /NS /NP
        New-Item -ItemType Directory -Force -Path (Join-Path $sharedPyDir "Lib\site-packages") | Out-Null

        if (Test-Path $sharedPyExe) {
            $pythonForVenv = $sharedPyExe
            Write-Host "[OK] Runtime de Python compartido listo en '$sharedPyDir'." -ForegroundColor Green
        }
    }
}

# 3. Crear entorno virtual
$VENV_DIR = Join-Path $BASE_DIR ".local\share\media_manager\venv"
$SCRIPTS_DIR = Join-Path $VENV_DIR "Scripts"
$VENV_PYTHON = Join-Path $SCRIPTS_DIR "python.exe"
$VENV_PIP = Join-Path $SCRIPTS_DIR "pip.exe"

Write-Host "[3/6] Configurando entorno virtual en '$VENV_DIR'..." -ForegroundColor Yellow
$recreateVenv = -not (Test-Path $VENV_PYTHON)
if (-not $recreateVenv) {
    $pyvenvCfg = Join-Path $VENV_DIR "pyvenv.cfg"
    if (Test-Path $pyvenvCfg) {
        $cfgContent = Get-Content $pyvenvCfg -Raw
        $expectedHome = Split-Path -Parent $pythonForVenv
        if ($cfgContent -notmatch [regex]::Escape($expectedHome)) {
            $recreateVenv = $true
        }
    }
}

if ($recreateVenv) {
    & $pythonForVenv -m venv --clear $VENV_DIR
}
Write-Host "[OK] Entorno virtual listo." -ForegroundColor Green

# 4. Instalar dependencias y paquete
Write-Host "[4/6] Instalando dependencias de Python y Media Manager..." -ForegroundColor Yellow
& $VENV_PYTHON -m pip install --upgrade pip --quiet
& $VENV_PYTHON -m pip install pirate-get --quiet
& $VENV_PYTHON -m pip install "$PSScriptRoot" --quiet
Write-Host "[OK] Paquetes instalados correctamente." -ForegroundColor Green

# 5. Configuracion y carpetas de medios
Write-Host "[5/6] Creando carpetas multimedia y configuracion en '$BASE_DIR'..." -ForegroundColor Yellow
$mediaPath = Join-Path $BASE_DIR "Media"
$downloadsPath = Join-Path $mediaPath "Downloads"
$moviesPath = Join-Path $mediaPath "Movies"
$showsPath = Join-Path $mediaPath "Shows"

New-Item -ItemType Directory -Force -Path $downloadsPath | Out-Null
New-Item -ItemType Directory -Force -Path $moviesPath | Out-Null
New-Item -ItemType Directory -Force -Path $showsPath | Out-Null

$configDir = Join-Path $BASE_DIR ".config\media_manager"
$configFile = Join-Path $configDir "config.yml"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

$dlPathYaml = $downloadsPath.Replace('\', '/')
$mediaPathYaml = $mediaPath.Replace('\', '/')
$defaultConfig = "download_path: $dlPathYaml`r`nmedia_path: $mediaPathYaml`r`n"

if (-not (Test-Path $configFile)) {
    Set-Content -Path $configFile -Value $defaultConfig -Encoding UTF8
    Write-Host "[OK] Archivo de configuracion generado en '$configFile'." -ForegroundColor Green
} else {
    Write-Host "[OK] Archivo de configuracion existente en '$configFile'." -ForegroundColor Green
}

# Si se instalo para todos los usuarios, limpiar/sincronizar posibles residuos de instalacion individual en el usuario actual
if ($installAllUsers -and ($BASE_DIR -ne $HOME)) {
    $userOldConfig = Join-Path $HOME ".config\media_manager\config.yml"
    if (Test-Path $userOldConfig) {
        Remove-Item -Path $userOldConfig -Force -ErrorAction SilentlyContinue
    }
    $userOldCmd = Join-Path $HOME ".local\bin\media-manager.cmd"
    if (Test-Path $userOldCmd) {
        Remove-Item -Path $userOldCmd -Force -ErrorAction SilentlyContinue
    }
}

# Generar hook silencioso para eventos de aria2c
Write-Host "Configurando hook silencioso en segundo plano..." -ForegroundColor Yellow
$env:MEDIA_MANAGER_HOME = $BASE_DIR
& $VENV_PYTHON -c "from media_manager.downloader import create_hook_script; create_hook_script()"
$hookBat = Join-Path $configDir "hook.bat"
if (Test-Path $hookBat) {
    Write-Host "[OK] Hook silencioso en segundo plano listo en '$hookBat'." -ForegroundColor Green
}
$oldHookExe = Join-Path $configDir "hook.exe"
if (Test-Path $oldHookExe) {
    Remove-Item -Path $oldHookExe -Force -ErrorAction SilentlyContinue
}

# Iniciar o recargar daemon de aria2c con el hook silencioso
Write-Host "Iniciando daemon de aria2c en segundo plano con hook silencioso..." -ForegroundColor Yellow
& $VENV_PYTHON -c "from media_manager.downloader import ensure_daemon; ensure_daemon()"
Write-Host "[OK] Daemon de aria2c activo y listo en segundo plano." -ForegroundColor Green

# 6. Configurar wrappers y variables de entorno PATH
Write-Host "[6/6] Configurando wrappers y variables de entorno PATH..." -ForegroundColor Yellow

$cmdWrapper = Join-Path $localBin "media-manager.cmd"
Set-Content -Path $cmdWrapper -Value "@echo off`r`n`"$VENV_PYTHON`" -m media_manager.cli %*" -Encoding ASCII

$pirateWrapper = Join-Path $localBin "pirate-get.cmd"
Set-Content -Path $pirateWrapper -Value "@echo off`r`n`"$VENV_PYTHON`" -m pirate.pirate %*" -Encoding ASCII

$aria2pWrapper = Join-Path $localBin "aria2p.cmd"
Set-Content -Path $aria2pWrapper -Value "@echo off`r`n`"$VENV_PYTHON`" -m aria2p %*" -Encoding ASCII

# Eliminar media-manager.ps1 para evitar que la ExecutionPolicy de PowerShell bloquee la ejecucion
$ps1Wrapper = Join-Path $localBin "media-manager.ps1"
if (Test-Path $ps1Wrapper) {
    Remove-Item -Path $ps1Wrapper -Force -ErrorAction SilentlyContinue
}

# Actualizar PATH del usuario actual y auto-inicio al iniciar sesion
$pywExe = Join-Path $SCRIPTS_DIR "pythonw.exe"
# Actualizar PATH del usuario actual y auto-inicio al iniciar sesion
$pywExe = Join-Path $SCRIPTS_DIR "pythonw.exe"
$runnerExe = if (Test-Path $pywExe) { $pywExe } else { $VENV_PYTHON }
$startDaemonBat = Join-Path $configDir "start_daemon.bat"
Set-Content -Path $startDaemonBat -Value "@echo off`r`n`"$runnerExe`" -c `"from media_manager.downloader import ensure_daemon; ensure_daemon()`"`r`n" -Encoding ASCII
$autostartCmd = "`"$runnerExe`" -c `"from media_manager.downloader import ensure_daemon; ensure_daemon()`""
Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "MediaManagerDaemon" -Value $autostartCmd -ErrorAction SilentlyContinue
Write-Host "[OK] Auto-inicio registrado para la sesion del usuario actual." -ForegroundColor Green

$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$userPathsList = @($userPath -split ';' | Where-Object { $_ -ne "" })

# Si es instalacion para todos los usuarios, remover del PATH del usuario la ruta del venv individual antiguo para evitar conflictos
if ($installAllUsers -and ($BASE_DIR -ne $HOME)) {
    $oldUserVenvScripts = Join-Path $HOME ".local\share\media_manager\venv\Scripts"
    $userPathsList = @($userPathsList | Where-Object { $_ -ne $oldUserVenvScripts })
}

$pathChanged = $false
if ($userPathsList -notcontains $localBin) {
    $userPathsList = @($localBin) + $userPathsList
    $pathChanged = $true
}
if ($userPathsList -notcontains $SCRIPTS_DIR) {
    $userPathsList = $userPathsList + $SCRIPTS_DIR
    $pathChanged = $true
}

if ($pathChanged -or $installAllUsers) {
    [System.Environment]::SetEnvironmentVariable("Path", ($userPathsList -join ';'), "User")
    Write-Host "[OK] Configurado '$localBin' en el PATH del usuario actual." -ForegroundColor Green
}

# Si es instalacion para todos los usuarios, configurar el PATH global (Machine) y la tarea programada de inicio del sistema (SYSTEM)
if ($installAllUsers) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $globalSetupBlock = @"
`$mp = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
`$list = @(`$mp -split ';' | Where-Object { `$_ -ne '' })
if (`$list -notcontains '$localBin') { `$list += '$localBin' }
if (`$list -notcontains '$SCRIPTS_DIR') { `$list += '$SCRIPTS_DIR' }
[System.Environment]::SetEnvironmentVariable('Path', (`$list -join ';'), 'Machine')
Set-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'MediaManagerDaemon' -Value '$autostartCmd' -ErrorAction SilentlyContinue
schtasks /Create /TN 'MediaManagerAria2' /TR '\"$startDaemonBat\"' /SC ONSTART /RU 'SYSTEM' /RL HIGHEST /F | Out-Null
schtasks /Run /TN 'MediaManagerAria2' | Out-Null
"@
    if ($isAdmin) {
        Invoke-Expression $globalSetupBlock
        Write-Host "[OK] Configurado PATH global y servicio de inicio del sistema (MediaManagerAria2)." -ForegroundColor Green
    } else {
        Write-Host "Solicitando permisos de Administrador para registrar el servicio de inicio del sistema y el PATH global..." -ForegroundColor Yellow
        try {
            $encodedCmd = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($globalSetupBlock))
            $proc = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encodedCmd" -Verb RunAs -Wait -PassThru -ErrorAction Stop
            if ($proc.ExitCode -eq 0) {
                Write-Host "[OK] Configurado PATH global y servicio de inicio del sistema (MediaManagerAria2)." -ForegroundColor Green
            } else {
                Write-Warning "No se pudo completar la configuracion global (codigo $($proc.ExitCode))."
            }
        } catch {
            Write-Warning "No se otorgaron permisos de Administrador para registrar la tarea de inicio del sistema. El auto-inicio por usuario (HKCU) igualmente quedo activo."
        }
    }
}

# Actualizar el PATH de la sesion actual
$env:Path = "$localBin;$SCRIPTS_DIR;$env:Path"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Instalacion completada con exito!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Alcance de instalacion:                      $modeLabel" -ForegroundColor Cyan
Write-Host "Las descargas provisionales se guardaran en: $downloadsPath" -ForegroundColor Cyan
Write-Host "Las peliculas y series organizadas iran a:   $mediaPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "Comandos disponibles:" -ForegroundColor Yellow
Write-Host "  media-manager                 -> Menu interactivo principal"
Write-Host "  media-manager search <nombre> -> Buscar torrents y descargarlos"
Write-Host "  media-manager status          -> Ver descargas activas"
Write-Host "  media-manager organize        -> Organizar descargas manualmente"
Write-Host "  media-manager download <link> -> Descargar enlace magnet o .torrent"
Write-Host ""
