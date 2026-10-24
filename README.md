# Media Manager (CLI + Desktop GUI con Flutter)

Herramienta multiplataforma (Windows, Linux y macOS) en Python y **Flutter (Flet)** para buscar, descargar (vía `aria2c` en segundo plano) y organizar automáticamente películas y series tanto desde una **Aplicación de Escritorio Nativa (GUI)** como desde su **Interfaz de Terminal Interactiva (TUI/CLI)**.

## Instalación

El instalador configura el servicio en segundo plano `aria2c`, los comandos de consola (`media-manager`, `media-manager-gui`) y **registra automáticamente la Aplicación de Escritorio en el sistema operativo**:
- **Windows:** Crea el acceso directo **Media Manager** en el **Menú Inicio** y en el **Escritorio** con su ícono personalizado, ejecutándose sin ventana de consola (`pythonw.exe`).
- **Linux:** Registra el lanzador `/usr/share/applications/media-manager.desktop` (o `~/.local/share/applications/media-manager.desktop`).
- **macOS:** Crea el paquete `/Applications/Media Manager.app` (o `~/Applications/Media Manager.app`).

Permite elegir entre:
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

Puedes usar **Media Manager** como **Aplicación de Escritorio (GUI con Flutter)** o desde la **Terminal (TUI/CLI)**. Ambas comparten el mismo motor `aria2c` en segundo plano en tiempo real.

### 🖥️ Aplicación de Escritorio (GUI con Flutter)
Puedes abrirla desde el ícono **Media Manager** en el **Menú Inicio / Escritorio / Aplicaciones**, o desde la terminal con:
```bash
media-manager gui
# o directamente:
media-manager-gui
```
La aplicación de escritorio cuenta con 4 secciones integradas en una interfaz oscura Material 3:
1. **📊 Descargas:** Tarjetas KPI en vivo (Activas, En pausa, Completadas, Velocidad global), barra para pegar enlaces Magnet/URL, selector nativo de archivos `.torrent`, y tarjetas de progreso en tiempo real con botones para **Pausar/Reanudar**, **Eliminar** (con confirmación y limpieza de archivos parciales), **Clear Completados** y **Organizar Ahora**.
2. **🔍 Buscador:** Búsqueda asíncrona de películas y series con indicadores visuales de salud de seeds (`Excelente`, `Buena`, `Baja`), selector de ordenamiento (**Seeders**, **Tamaño**, **Nombre**), descarga en 1 clic o casillas de selección múltiple (`Descargar Marcados`).
3. **🎞 Biblioteca:** Explorador visual de tu colección organizada en `Movies/` y `Shows/` con conteo de temporadas, episodios, tamaños y botón para abrir cada carpeta en el explorador del sistema.
4. **⚙️ Ajustes:** Selector gráfico de carpetas (`download_path` y `media_path`), estado y reinicio del daemon `aria2c`, y botón para reinstalar los accesos directos del sistema (`media-manager gui --install-shortcut`).

---

### ⌨️ Uso desde la Terminal (TUI / CLI)

El ejecutable se llama `media-manager`. Al ejecutarlo sin argumentos (`media-manager`), abre el **Panel Principal Interactivo** con métricas en tiempo real del daemon `aria2c` y acceso rápido por teclado (`↑/↓`, `1-7`, `B` Buscar, `V` Visor de descargas, `M` Agregar magnet, `O` Organizar, `C` Limpiar completados, `G` Abrir App GUI).

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
