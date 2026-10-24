# Media Manager CLI

Herramienta de línea de comandos en Python para buscar, descargar (vía `aria2c` en segundo plano) y organizar automáticamente películas y series.

## Instalación

El instalador permite elegir entre:
1. **Solo para el usuario actual** (`$HOME` / `%USERPROFILE%`)
2. **Para todos los usuarios** (`C:\Users\Public` en Windows, `/Users/Shared` en macOS o `/srv/public` en Linux)

### Windows (PowerShell)
1. Abre PowerShell en la carpeta del proyecto.
2. Ejecuta el instalador:
   ```powershell
   # Pregunta interactivamente el alcance de instalacion (Usuario actual o Todos los usuarios)
   .\install.ps1

   # O especificando el modo directamente:
   .\install.ps1 -AllUsers
   .\install.ps1 -CurrentUser
   ```
   *(El script instalará automáticamente `aria2` mediante WinGet/Chocolatey si no está presente, configurará el entorno virtual con todas las dependencias, creará las carpetas multimedia y agregará `media-manager` al PATH. Cuando se elige `-AllUsers`, toda la estructura `.local`, `.config` y `Media` se instala en `C:\Users\Public` para que cualquier usuario del equipo pueda usarla).*

### Linux / macOS (Bash)
1. Clona el repositorio o ubícate en la carpeta `media_manager`.
2. Ejecuta el instalador:
   ```bash
   # Interactivo:
   ./install.sh

   # O especificando el modo directamente:
   ./install.sh --all-users
   ./install.sh --current-user
   ```

## Configuración 

La configuración principal se genera automáticamente durante la instalación o la primera vez que inicia el programa:
- **Instalación para todos los usuarios (Windows):** `C:\Users\Public\.config\media_manager\config.yml`
- **Instalación por usuario:** `~/.config/media_manager/config.yml`

El archivo de configuración tiene la siguiente estructura:
```yaml
# En instalacion para todos los usuarios (Public):
download_path: C:/Users/Public/Media/Downloads
media_path: C:/Users/Public/Media

# En instalacion de usuario individual:
download_path: ~/Media/Downloads
media_path: ~/Media
```
*(Se expanden automáticamente rutas con `~`, `$HOME`, `$PUBLIC`, `%USERPROFILE%` o `%PUBLIC%`).*


## Uso

El ejecutable se llama `media-manager`. Al ejecutarlo sin argumentos (`media-manager`), abre el **Panel Principal Interactivo** con métricas en tiempo real del daemon `aria2c` y acceso rápido por teclado (`↑/↓`, `1-6`, `B` Buscar, `V` Visor de descargas, `M` Agregar magnet, `O` Organizar, `C` Limpiar completados).

También proporciona los siguientes comandos directos:

### 1. Buscador interactivo de torrents
```bash
media-manager search "Query de búsqueda"
```
Abre el **Buscador de Torrents TUI**, donde puedes:
- Navegar resultados paginados con `↑` / `↓` / `PgUp` / `PgDn` viendo salud de seeds (`Excelente`, `Buena`, `Baja`), tamaño, seeders, leechers, fecha e inspector completo abajo.
- Presionar `Espacio` para **marcar múltiples torrents (`☑`)** (por ejemplo, varias temporadas o episodios a la vez) y `Enter` para enviarlos todos a descargar.
- Presionar `O` para cambiar el orden en vivo (**Seeders**, **Tamaño** o **Nombre**).
- Presionar `N` para realizar una nueva búsqueda sin salir de la interfaz.

### 2. Pegar enlaces Magnet o abrir archivos .torrent
Puedes agregar descargas directamente indicando la opción `-f` o el comando `download`:
```bash
# Mediante la opción -f (archivos .torrent o enlaces magnet)
media-manager -f archivo.torrent
media-manager -f "magnet:?xt=urn:btih:..."

# O mediante el comando download
media-manager download "magnet:?xt=urn:btih:..."
media-manager download archivo.torrent
```
También puedes presionar `M` (o la opción `3`) en el Panel Principal al ejecutar `media-manager` sin argumentos (soporta pegar con `Ctrl+V` o clic derecho).

### 3. Visor y gestor interactivo de descargas
```bash
media-manager status
```
Abre el visor interactivo de descargas integrado (en tiempo real), donde se visualiza:
- **Nombre** del torrent o archivo
- **Estado** (`Activo`, `Pausado (Inactivo)`, `En cola (Inactivo)`, `Completado`, `Error`)
- **Progreso** (barra visual y porcentaje)
- **Tamaño** descargado y tamaño total (`MB` / `GB`)
- **Velocidad**, **Seeds/Peers** y **ETA** (tiempo estimado restante)

**Atajos dentro del visor (`media-manager status`):**
- `↑` / `↓` (o `1`-`9`): Seleccionar una descarga
- `P` o `Espacio`: Poner en pausa o reanudar la descarga seleccionada
- `D` o `Supr`: Eliminar una descarga en particular (con confirmación)
- `C`: Hacer *clear* (limpiar) todas las descargas completadas
- `A`: Pausar o reanudar todas las descargas
- `O`: Organizar descargas manualmente
- `Q` o `Esc`: Salir del visor

También puedes gestionar las descargas directamente por comandos:
```bash
media-manager pause <#|GID|nombre|all>
media-manager resume <#|GID|nombre|all>
media-manager remove <#|GID|nombre>
media-manager clear
```

### 4. Organizar las descargas
```bash
media-manager organize
```
Escanea `download_path` en busca de descargas completadas y las mueve a `media_path`. Ocurre automáticamente gracias al hook de eventos, pero puedes ejecutarlo manualmente si alguna vez es necesario.

- Usa `guessit` para extraer metadatos del nombre del archivo.
- Mueve el contenido automáticamente:
  - **Series:** `<media_path>/Shows/<Nombre de Serie>/Season <N>/`
  - **Películas:** `<media_path>/Movies/<Nombre> (<Año>)/`
- Si encuentra subtítulos (srt, vtt, etc.), los mueve junto a la película o episodio.
- El resto de archivos (nfo, txt, carpetas vacías) se mueven a `<media_path>/.trash` automáticamente.

*(Nota: En versiones anteriores de esta aplicación había un comando `daemon`, pero ha sido reemplazado por un sistema infinitamente más eficiente usando funciones nativas de `aria2c` bajo eventos (hook `--on-download-complete`), por lo cual todo estará automatizado sin desgastar procesos innecesarios).*
