# Media Manager CLI

Herramienta de línea de comandos en Python para buscar, descargar (vía `aria2c` en segundo plano) y organizar automáticamente películas y series.

## Instalación

1. Clona el repositorio o ubícate en la carpeta `media_manager`.
2. Ejecuta el instalador:
   ```bash
   ./install.sh
   ```
   *(Este script instalará `aria2` mediante apt, junto con todas las dependencias de Python como `pirate-get`, e instalará la aplicación en `~/.local/bin/`).*
3. Asegúrate de añadir `~/.local/bin` a tu variable PATH.

## Configuración 

La configuración principal se genera automáticamente la primera vez que inicia el programa. Se guardará en:
`~/.config/media_manager/config.yml`

El archivo de configuración tiene la siguiente estructura:
```yaml
download_path: $HOME/Media/Downloads   # Ruta de descargas provisionales
media_path: $HOME/Media                # Ruta de destino final multimedia
```
*(Puedes usar variables de entorno como `$HOME`).*

## Uso

El ejecutable se llama `media-manager` y proporciona los siguientes comandos:

### 1. Buscar y descargar
```bash
media-manager search "Query de búsqueda"
```
Abrirá la interfaz de `pirate-get` para buscar torrents. Al elegir uno, se enviará el enlace magnet o torrent automáticamente al daemon de `aria2c` bajo la ruta de descargas (en modo *detached*).

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
También puedes seleccionar la opción **🧲 Add Magnet Link / Torrent File** en el menú interactivo al ejecutar `media-manager` sin argumentos.

### 3. Ver estado de descargas
```bash
media-manager status
```
Abre la interfaz TUI de `aria2p` (similar a `top`) para ver el progreso de los archivos que se están descargando.

### 4. Organizar las descargas
```bash
media-manager organize
```
Escanea `download_path` en busca de descargas completadas y las mueve a `media_path`. Ocurre automáticamente gracias al hook de eventos, pero puedes ejecutarlo manualmente si alguna vez es necesario.

- Usa `guessit` para extraer metadatos del nombre del archivo.
- Mueve el contenido automáticamente:
  - **Series:** `$HOME/Media/Shows/<Nombre de Serie>/Season <N>/`
  - **Películas:** `$HOME/Media/Movies/<Nombre> (<Año>)/`
- Si encuentra subtítulos (srt, vtt, etc.), los mueve junto a la película o episodio.
- El resto de archivos (nfo, txt, carpetas vacías) se mueven a `~/.trash` automáticamente.

*(Nota: En versiones anteriores de esta aplicación había un comando `daemon`, pero ha sido reemplazado por un sistema infinitamente más eficiente usando funciones nativas de `aria2c` bajo eventos (hook `--on-download-complete`), por lo cual todo estará automatizado sin desgastar procesos innecesarios).*
