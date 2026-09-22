# PowerShell Installer for Media Manager CLI on Windows
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Instalador de Media Manager CLI (Windows)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar e instalar aria2c
Write-Host "[1/6] Verificando dependencia del sistema: aria2c..." -ForegroundColor Yellow

$aria2Found = $null
if (Get-Command aria2c -ErrorAction SilentlyContinue) {
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
} else {
    Write-Host "[OK] aria2c encontrado: $aria2Found" -ForegroundColor Green
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

# 3. Crear entorno virtual
$VENV_DIR = Join-Path $HOME ".local\share\media_manager\venv"
$SCRIPTS_DIR = Join-Path $VENV_DIR "Scripts"
$VENV_PYTHON = Join-Path $SCRIPTS_DIR "python.exe"
$VENV_PIP = Join-Path $SCRIPTS_DIR "pip.exe"

Write-Host "[3/6] Configurando entorno virtual en '$VENV_DIR'..." -ForegroundColor Yellow
if (-not (Test-Path $VENV_PYTHON)) {
    & $pythonExe -m venv $VENV_DIR
}
Write-Host "[OK] Entorno virtual listo." -ForegroundColor Green

# 4. Instalar dependencias y paquete
Write-Host "[4/6] Instalando dependencias de Python y Media Manager..." -ForegroundColor Yellow
& $VENV_PIP install --upgrade pip --quiet
& $VENV_PIP install pirate-get --quiet
& $VENV_PIP install "$PSScriptRoot" --quiet
Write-Host "[OK] Paquetes instalados correctamente." -ForegroundColor Green

# 5. Configuracion y carpetas de medios en la carpeta de usuario
Write-Host "[5/6] Creando carpetas multimedia y configuracion en usuario..." -ForegroundColor Yellow
$mediaPath = Join-Path $HOME "Media"
$downloadsPath = Join-Path $mediaPath "Downloads"
$moviesPath = Join-Path $mediaPath "Movies"
$showsPath = Join-Path $mediaPath "Shows"

New-Item -ItemType Directory -Force -Path $downloadsPath | Out-Null
New-Item -ItemType Directory -Force -Path $moviesPath | Out-Null
New-Item -ItemType Directory -Force -Path $showsPath | Out-Null

$configDir = Join-Path $HOME ".config\media_manager"
$configFile = Join-Path $configDir "config.yml"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

if (-not (Test-Path $configFile)) {
    $defaultConfig = "download_path: ~/Media/Downloads`r`nmedia_path: ~/Media`r`n"
    Set-Content -Path $configFile -Value $defaultConfig -Encoding UTF8
    Write-Host "[OK] Archivo de configuracion generado en '$configFile'." -ForegroundColor Green
} else {
    Write-Host "[OK] Archivo de configuracion ya existe en '$configFile'." -ForegroundColor Green
}

# Generar hook silencioso para eventos de aria2c
Write-Host "Configurando hook silencioso en segundo plano..." -ForegroundColor Yellow
& $VENV_PYTHON -c "from media_manager.downloader import create_hook_script; create_hook_script()"
$hookExe = Join-Path $configDir "hook.exe"
if (Test-Path $hookExe) {
    Write-Host "[OK] Hook silencioso en segundo plano listo en '$hookExe'." -ForegroundColor Green
}

# Iniciar o recargar daemon de aria2c con el hook silencioso
Write-Host "Iniciando daemon de aria2c en segundo plano con hook silencioso..." -ForegroundColor Yellow
& $VENV_PYTHON -c "from media_manager.downloader import ensure_daemon; ensure_daemon()"
Write-Host "[OK] Daemon de aria2c activo y listo en segundo plano." -ForegroundColor Green

# 6. Configurar PATH del usuario y accesos directos
Write-Host "[6/6] Configurando variables de entorno PATH..." -ForegroundColor Yellow

$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$userPathsList = $userPath -split ';' | Where-Object { $_ -ne "" }

if ($userPathsList -notcontains $SCRIPTS_DIR) {
    $newUserPath = ($userPathsList + $SCRIPTS_DIR) -join ';'
    [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    Write-Host "[OK] Agregado '$SCRIPTS_DIR' al PATH de usuario." -ForegroundColor Green
} else {
    Write-Host "[OK] '$SCRIPTS_DIR' ya esta en el PATH de usuario." -ForegroundColor Green
}

# Crear carpeta ~/.local/bin con wrappers para compatibilidad
$localBin = Join-Path $HOME ".local\bin"
New-Item -ItemType Directory -Force -Path $localBin | Out-Null

$cmdWrapper = Join-Path $localBin "media-manager.cmd"
Set-Content -Path $cmdWrapper -Value "@echo off`r`n`"$VENV_PYTHON`" -m media_manager.cli %*" -Encoding ASCII

# Eliminar media-manager.ps1 para evitar que la ExecutionPolicy de PowerShell bloquee la ejecucion
$ps1Wrapper = Join-Path $localBin "media-manager.ps1"
if (Test-Path $ps1Wrapper) {
    Remove-Item -Path $ps1Wrapper -Force -ErrorAction SilentlyContinue
}

if ($userPathsList -notcontains $localBin) {
    $currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    [System.Environment]::SetEnvironmentVariable("Path", "$localBin;$currentUserPath", "User")
}

# Actualizar el PATH de la sesion actual
if ($env:Path -split ';' -notcontains $SCRIPTS_DIR) {
    $env:Path = "$SCRIPTS_DIR;$localBin;$env:Path"
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Instalacion completada con exito!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
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
