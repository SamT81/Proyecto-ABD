# Entrega 2: adquisición y verificación del MGN y filtro PDET

Parte de la Entrega 2 que cubre el criterio **Data Acquisition & Verification: documentación de los mecanismos
de descarga y de los controles de calidad**. La salida de esta parte es la entrada del ETL de integridad
(`src/01_load_municipalities.py`).

## Fuentes

| Fuente | Archivo | Uso |
|---|---|---|
| DANE, MGN2025, nivel municipio ([geoportal](https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111)) | `MGN2025_MPIO_GRAFICO.zip` (71.6 MB, Shapefile, WGS84) | Límites municipales |
| Agencia de Renovación del Territorio, municipios PDET (Decreto 893 de 2017) | `config/pdet/MunicipiosPDET.xlsx` | Listado de 170 municipios y su subregión |

En el plan de la Entrega 1 se previó descargar el ZIP completo del MGN2025 (1.5 GB, todos los niveles). El
geoportal publica el **nivel municipio por separado** con la misma versión y la misma capa, así que se descarga solo
ese archivo (unas 20 veces más pequeño). Es el mismo criterio de "filtrar en origen" del plan.

## Qué hace cada archivo

| Archivo | Función |
|---|---|
| `config/acquisition.yaml` | URL, rutas, SHA-256 y tamaño fijados, conteos esperados y umbrales de calidad. |
| `src/00a_download_mgn.py` | Descarga por bloques (reanudable, con reintentos), verifica tamaño, SHA-256 y CRC del ZIP, extrae y escribe el manifiesto. |
| `src/00b_build_pdet_catalog.py` | Convierte el Excel de la ART a `config/pdet/pdet_municipios.csv` (códigos a 5 dígitos, id de subregión). |
| `src/00c_filter_pdet.py` | Verifica la capa del MGN, la cruza con el listado PDET, ejecuta los controles y escribe `data/mgn_pdet_2025.gpkg`. |
| `src/mgn_acquisition.py` | Funciones compartidas (normalización de códigos y nombres, controles). No usa red ni MongoDB. |
| `tests/test_mgn_acquisition.py` | Pruebas con datos sintéticos. |
| `docs/calidad/manifest_mgn.json` | Evidencia de la descarga: URL, fecha, cabeceras HTTP, tamaño, SHA-256 del ZIP y de cada archivo extraído. |
| `docs/calidad/qc_mgn_pdet.md` / `.json` | Resultado de todos los controles de calidad. |

## Cómo ejecutarlo

```bash
pip install -r requirements.txt openpyxl     # openpyxl solo para leer el Excel de la ART
python src/00a_download_mgn.py               # descarga y verifica (si ya existe, solo verifica)
python src/00b_build_pdet_catalog.py         # opcional: el CSV ya está versionado
python src/00c_filter_pdet.py                # filtro PDET + controles -> data/mgn_pdet_2025.gpkg
python src/01_load_municipalities.py         # ETL de integridad y carga (rama feat/pdet-integrity-etl)
python -m pytest tests/test_mgn_acquisition.py -q
```

`00a` reutiliza el ZIP si ya está descargado; `--force` lo vuelve a bajar y `--verify` solo verifica. Cada script
termina con código 1 si un control queda en FALLA, así que la cadena se detiene antes de cargar datos dudosos.

## Mecanismo de descarga y verificación de integridad

1. Descarga HTTP por bloques de 1 MB a un archivo `.part`; si se corta, el siguiente intento pide solo lo que falta
   (`Range`). El archivo solo toma su nombre final cuando el tamaño coincide con `Content-Length`.
2. Se calcula el **SHA-256** del ZIP y se compara con el valor fijado en `config/acquisition.yaml`
   (`a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f`, 71 576 494 bytes). El DANE no publica un
   checksum oficial, por eso el valor se fijó en la primera descarga (08/11/2026) junto con `Last-Modified` y `ETag`
   del servidor. Si el DANE reemplaza el archivo, la verificación falla y el cambio se revisa antes de actualizar el
   valor; así todo el equipo trabaja con exactamente los mismos bytes.
3. Se comprueba el CRC de cada archivo del ZIP y que estén los componentes del shapefile (`.shp`, `.shx`, `.dbf`,
   `.prj`, `.cpg`).
4. Se extrae y se guarda el SHA-256 de cada archivo extraído. `00c` lo vuelve a calcular antes de leer, de modo que
   el filtro nunca corre sobre archivos modificados después de la descarga.

## Controles de calidad

Resultado de la corrida del 08/11/2026: **31 OK, 1 AVISO, 0 FALLA** (detalle en `docs/calidad/qc_mgn_pdet.md`).

| Grupo | Controles |
|---|---|
| Fuente (SRC) | SHA-256 del ZIP verificado; archivos extraídos sin cambios. |
| Capa MGN (MGN) | Campos requeridos; CRS EPSG:4326; 1 122 unidades; `mpio_cdpmp` único, de 5 dígitos y igual a `dpto_ccdgo + mpio_ccdgo`; sin nulos; extensión dentro de la caja de Colombia. |
| Listado PDET (PDET) | 170 municipios; códigos únicos y de 5 dígitos; 16 subregiones; prefijo del municipio = departamento; sin nulos. |
| Cruce (JOIN) | Los 170 códigos existen en el MGN; departamento coincide; nombre coincide sin tildes (aviso). |
| Geometría (GEO) | 170 polígonos, uno por código; solo Polygon/MultiPolygon; no vacíos; válidos (OGC); área en EPSG:9377 vs `mpio_narea` del DANE (< 1 %); sin solapes entre vecinos; tamaño del documento frente al límite BSON de 16 MB. |
| Salida (OUT) | El GeoPackage se relee con los mismos 170 códigos, en EPSG:4326 y sin nulos. |

Hallazgos:

* **El cruce se hace por código DIVIPOLA, no por nombre.** En el Excel de la ART los códigos de Antioquia aparecen
  sin el cero inicial (`5490` en vez de `05490`); se normalizan a 5 dígitos.
* **Seis nombres difieren** entre la ART y el MGN2025 (el único AVISO): `19418` López / López de Micay, `19548`
  Piendamó / Piendamó - Tunía, `50711` Vista Hermosa / Vistahermosa, `70523` San Antonio de Palmito / Palmito,
  `70823` Tolú Viejo / San José de Toluviejo y `86573` Leguízamo / Puerto Leguízamo. Son el mismo municipio con
  el nombre oficial actualizado; se conserva el nombre del MGN.
* Las 170 geometrías son válidas, sin solapes (339 pares de vecinos revisados) y su área en EPSG:9377 coincide con
  `mpio_narea` del DANE. En el shapefile 168 son Polygon y 2 MultiPolygon; en el GeoPackage de salida las 170
  quedan como MultiPolygon (tipo único de capa), que es el tipo definido en el esquema de `municipalities`.
* El municipio más pesado (`18756`, Solano) tiene 51 716 vértices y unos 2.2 MB en GeoJSON, lejos del límite de
  16 MB de MongoDB; no hace falta simplificar ni partir geometrías.
* Los 170 municipios PDET suman **389 182 km²**.

## Contrato de salida

`data/mgn_pdet_2025.gpkg`, capa `municipios_pdet`, EPSG:4326, 170 registros:

| Campo | Tipo | Descripción |
|---|---|---|
| `mpio_cdpmp` | texto (5) | Código DIVIPOLA del municipio. Será el `_id` en `municipalities`. |
| `mpio_cnmbr` | texto | Nombre oficial del municipio (MGN). |
| `dpto_ccdgo`, `mpio_ccdgo` | texto (2), (3) | Códigos de departamento y municipio. |
| `dpto_cnmbr` | texto | Nombre del departamento. |
| `mpio_tipo` | texto | Tipo de entidad (los 170 son `MUNICIPIO`). |
| `mpio_narea` | real | Área oficial en km² publicada por el DANE. |
| `pdet_subregion_id`, `pdet_subregion` | entero, texto | Subregión PDET (1 a 16, orden alfabético). |
| `mgn_version` | texto | `MGN2025`. |
| `geometry` | MultiPolygon | Límite municipal. |

El ETL lo lee con sus valores por defecto. También puede leer el shapefile nacional y filtrar con el catálogo:
`python src/01_load_municipalities.py --input data/raw/mgn2025_mpio/MGN_ADM_MPIO_GRAFICO.shp --pdet-csv config/pdet/pdet_municipios.csv`.
Ambas formas se probaron con `--dry-run` y dan 170 municipios válidos.
