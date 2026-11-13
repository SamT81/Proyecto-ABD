# Entrega 3: adquisición y verificación de las huellas de edificios

Parte de la Entrega 3 que cubre **Data Acquisition & Verification** para los dos datasets seleccionados en la
Entrega 1 (Microsoft Building Footprints y Google Open Buildings). La salida de esta parte son los archivos
crudos verificados en `data/raw/`, que son la entrada del ETL (`src/01b_etl_buildings.py`, rama
`feat/buildings-etl`).

## Fuentes

| Fuente | Partición | Índice usado para seleccionar | Verificación oficial |
|---|---|---|---|
| Microsoft Global ML Building Footprints ([Planetary Computer](https://planetarycomputer.microsoft.com/dataset/ms-buildings)), ODbL | País + quadkey de nivel 9 (teselas Web Mercator de ~78 km de lado en el ecuador). GeoJSON por líneas en `.csv.gz`. | [`dataset-links.csv`](https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv): país, quadkey, URL y tamaño redondeado | `Content-MD5` y `Content-Length` del servidor (Azure Blob) |
| Google Open Buildings v3 ([sitio](https://sites.research.google/gr/open-buildings/)), CC BY 4.0 y ODbL | Celdas S2 de nivel 4. CSV con geometría WKT en `.csv.gz`. | [`tiles.geojson`](https://openbuildings-public-dot-gweb-research.uw.r.appspot.com/public/tiles.geojson): polígono de cada celda | `md5Hash` y `size` del listado del bucket público `open-buildings-data` (API JSON de Cloud Storage) |

Ninguna de las dos fuentes se descarga completa. Siguiendo el criterio de "filtrar en origen" del plan de la
Entrega 1, se cruzan los índices con los 170 polígonos PDET de la Entrega 2 y solo se bajan las particiones que
los tocan:

| | Microsoft | Google |
|---|---|---|
| Particiones del país / del dataset | 232 quadkeys de Colombia (~679 MB) | 333 celdas S2 en el mundo (178.3 GB) |
| Particiones que tocan PDET | **125** | **8** (`8e1`, `8e3`, `8e5`, `8e7`, `8e9`, `8ef`, `91d`, `91f`) |
| Tamaño descargado | 373.4 MB (1.6 GB descomprimido) | 3 110.1 MB (8.1 GB descomprimido) |
| Registros en los archivos | 4 595 615 | 31 499 115 |
| Municipios PDET por partición | 1 a 15 (mediana 3) | 1 a 82 (mediana 11) |

Las celdas de Google son mucho más grandes que los quadkeys de Microsoft (una celda S2 de nivel 4 cubre unos
330 000 km²) y además incluyen edificios de Venezuela, Ecuador y Panamá; el ETL descarta lo que queda fuera de
PDET antes de interpretar la geometría.

## Qué hace cada archivo

| Archivo | Función |
|---|---|
| `config/buildings.yaml` | URL de los índices, carpetas, margen de selección, hilos de descarga y rutas de los reportes. |
| `src/00d_select_building_partitions.py` | Descarga los índices, cruza quadkeys y celdas S2 con los polígonos PDET y escribe el catálogo. |
| `config/buildings/particiones_pdet.csv` | Catálogo versionado: fuente, partición, URL, tamaño, MD5 publicado, caja envolvente y municipios PDET que toca. Es la lista exacta que baja `00e`. |
| `src/00e_download_buildings.py` | Descarga en paralelo (4 hilos), reanuda descargas cortadas y verifica cada archivo. |
| `src/buildings_acquisition.py` | Funciones compartidas: geometría de los quadkeys, selección, MD5 en base64, integridad gzip. No usa MongoDB. |
| `tests/test_buildings_acquisition.py` | Pruebas sin red con datos sintéticos (quadkeys, selección, cobertura, gzip cortado). |
| `docs/calidad/manifest_buildings.json` | Evidencia por archivo: URL, fecha, `Last-Modified`/`ETag`, tamaño, MD5 esperado y obtenido, SHA-256, registros. |
| `docs/calidad/qc_buildings_acquisition.md` / `.json` | Resultado de los controles de selección y de descarga. |

## Cómo ejecutarlo

```bash
python src/00c_filter_pdet.py                       # Entrega 2: genera data/mgn_pdet_2025.gpkg
python src/00d_select_building_partitions.py        # catálogo de particiones (--refresh vuelve a bajar los índices)
python src/00e_download_buildings.py                # descarga y verifica (~3.5 GB)
python src/00e_download_buildings.py --verify       # solo verifica lo que ya está en data/raw
python -m pytest tests/test_buildings_acquisition.py -q
```

`00e` reutiliza un archivo si ya existe y su MD5 coincide con el publicado; si la fuente lo reemplaza, se vuelve a
bajar. `--source microsoft|google` limita a una fuente y `--limit N` baja solo N archivos por fuente (útil para
probar). Con una conexión de ~20 MB/s la descarga completa tomó unos 3 minutos. Si algún archivo falla por la red
queda como `error` en el manifiesto y el script termina con código 1; basta con volver a ejecutarlo.

## Selección de particiones

1. Microsoft: cada quadkey se convierte en su caja lon/lat (tesela Web Mercator) y se cruza con los municipios
   PDET. Solo se consideran las filas del índice con `Location = Colombia`: Microsoft separa los archivos por
   país, de modo que un quadkey de frontera tiene un archivo para Colombia y otro para el país vecino.
2. Google: se cruzan los polígonos de `tiles.geojson` con los municipios PDET y se completa cada celda con el
   tamaño y el MD5 del listado del bucket.
3. El cruce usa los municipios ampliados en 0.01° (~1 km). Un edificio se asigna al municipio por su punto
   representativo, pero la fuente lo pudo guardar en la partición vecina; el margen evita perderlo.

## Verificación de integridad

| Control | Cómo se hace |
|---|---|
| Tamaño | Igual al `Content-Length` del servidor (HEAD antes de bajar). En Google también igual al `size` del bucket; en Microsoft dentro del redondeo del índice (publica "4.5MB"). |
| MD5 | Se calcula en base64 y se compara con `md5Hash` (Google) o `Content-MD5` (Microsoft). |
| Integridad gzip | Se descomprime cada archivo completo en streaming: detecta archivos truncados o con CRC incorrecto. |
| Formato | Primera línea: cabecera `latitude,longitude,area_in_meters,confidence,geometry,full_plus_code` en Google; `Feature` GeoJSON con `Polygon` en Microsoft. |
| Registros | Número de líneas (menos la cabecera en Google); ningún archivo vacío. |
| SHA-256 | Se guarda en el manifiesto para que el ETL y la carga registren exactamente qué bytes procesaron (`ingestion_log.checksum`). |

Las descargas van a un archivo `.part` y solo toman su nombre final cuando el tamaño coincide; si se cortan, el
siguiente intento pide lo que falta con `Range`.

## Resultados (13/11/2026)

Selección: **10 OK, 0 AVISO, 0 FALLA**. Descarga: **14 OK, 0 AVISO, 0 FALLA**. Detalle en
`docs/calidad/qc_buildings_acquisition.md`.

* **Cobertura completa:** los 170 municipios PDET quedan cubiertos por al menos una partición de cada fuente.
* **MD5:** los 8 archivos de Google y 95 de los 125 de Microsoft coinciden con el MD5 publicado. Los otros 30
  de Microsoft (todos de más de 4 MB) no traen `Content-MD5`, porque Azure solo lo publica para blobs subidos en
  una sola operación; para ellos la verificación es el tamaño exacto contra el servidor y el CRC del gzip.
* **Versiones:** los archivos de Microsoft tienen `Last-Modified` del 03/02/2026 (índice subido el 23/02/2026);
  los de Google, del 23/06/2023 (versión 3). Si cualquiera de las dos fuentes publica una versión nueva, el MD5
  cambia y `00e` vuelve a descargar el archivo y lo registra en el manifiesto.
* Microsoft trae `height` y `confidence` en las propiedades, pero `height` vale `-1` (sin dato) en todos los
  registros descargados y `confidence` solo tiene valor en 176 de 4 595 615. Por eso el esquema de
  `buildings_microsoft` no los incluye y el umbral de confianza solo se aplica a Google.

## Contrato de salida

Archivos crudos en `data/raw/microsoft/<quadkey>_<archivo>.csv.gz` y `data/raw/google/<celda>_buildings.csv.gz`
(ignorados por git), listados en `config/buildings/particiones_pdet.csv` y verificados en
`docs/calidad/manifest_buildings.json`. El ETL solo procesa archivos que aparezcan en el manifiesto con estado
`descargado` o `reutilizado`, y guarda su SHA-256 junto a la salida.
