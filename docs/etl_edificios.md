# Entrega 3: ETL de huellas de edificios

Parte de la Entrega 3 que cubre **Data Integrity & Format** para las dos fuentes de edificios: convierte los
archivos crudos verificados por la adquisición (`docs/adquisicion_edificios.md`) en GeoParquet limpio, con un
documento por edificio y los campos exactos de `buildings_microsoft` y `buildings_google` definidos en la
Entrega 1. La carga a MongoDB y la creación de índices (rama `feat/buildings-load`) leen esta salida.

## Qué hace cada archivo

| Archivo | Función |
|---|---|
| `config/buildings.yaml` (sección `etl`) | Carpeta de salida, tamaño de bloque, tamaño de row group, decimales y margen de prefiltro. |
| `src/01b_etl_buildings.py` | Orquesta el ETL en paralelo (un proceso por partición), reutiliza particiones ya procesadas, relee y valida la salida y escribe el reporte. |
| `src/buildings_etl.py` | Lectura por bloques, limpieza de geometrías, asignación de municipio, área y escritura. Incluye `iter_documents()` para la carga. No usa MongoDB. |
| `tests/test_buildings_etl.py` | Pruebas con datos sintéticos (asignación en bordes, reparación, redondeo, áreas, lectores, salida). |
| `docs/calidad/etl_buildings_report.md` / `.json` | Resultado de la corrida: conteos por fuente y partición, rechazos por motivo, edificios por municipio y controles. |

## Cómo ejecutarlo

```bash
python src/00e_download_buildings.py --verify    # los archivos crudos deben estar verificados
python src/01b_etl_buildings.py                  # ambas fuentes (reutiliza particiones ya procesadas)
python src/01b_etl_buildings.py --source google --force
python src/01b_etl_buildings.py --partition 8e1 032212333    # prueba rápida con dos particiones
python -m pytest tests/test_buildings_etl.py -q
```

## Transformación de cada edificio

1. **Lectura por bloques de 200 000 filas.** Nunca se carga un archivo completo en memoria (las celdas de
   Google pesan hasta 1.8 GB descomprimidas). Microsoft se lee línea a línea y se interpreta con
   `shapely.from_geojson` vectorizado; Google con `pandas.read_csv(chunksize=...)`.
2. **Prefiltro (solo Google).** Cada fila trae la latitud y longitud de su centroide. Antes de interpretar el WKT
   se descartan las filas cuyo centroide está a más de 0.002° (~220 m) de cualquier municipio PDET. Así no se
   construyen geometrías para los edificios de Venezuela, Ecuador o del resto de Colombia que traen las celdas.
3. **Reparación.** Las geometrías inválidas se reparan con `make_valid`; si el resultado tiene varias partes se
   conserva el polígono de mayor área (el esquema define `Polygon`). `is_valid_geom` queda en `false` para estos
   edificios, como define el diccionario de datos.
4. **Asignación de municipio.** Se calcula el punto representativo (`point_on_surface`, siempre dentro del
   polígono) y se busca el municipio que lo contiene: un `STRtree` descarta por caja envolvente y la prueba
   exacta se hace con `intersects_xy` sobre los polígonos PDET preparados. Cada edificio queda en un solo
   municipio, también los que cruzan un límite. Los que no caen en ningún municipio PDET se descartan.
5. **Área.** Se mide en EPSG:9377 (MAGNA-SIRGAS Origen Nacional) sobre la geometría reparada, antes de redondear.
   En Microsoft es el `area_m2` del documento; en Google se conserva `area_in_meters` (como define el esquema) y
   el área en EPSG:9377 se usa para verificarla.
6. **Formato para 2dsphere.** Coordenadas a 6 decimales (~0.1 m) con `set_precision`, que ajusta a la grilla sin
   romper la validez, y anillo exterior en sentido antihorario (regla de la mano derecha de GeoJSON).
7. **Escritura.** GeoParquet (WKB, EPSG:4326, compresión zstd) en row groups de 50 000 filas, primero en una
   carpeta `.tmp` que se renombra al terminar la partición. Una corrida cortada no deja archivos a medias.

## Eficiencia

* Un proceso por partición (4 en paralelo, `load.workers` de `config/params.yaml`); las particiones grandes se
  reparten primero.
* Operaciones vectorizadas de shapely 2 sobre bloques completos; las únicas iteraciones en Python son sobre los
  pocos edificios multiparte.
* Prefiltro por coordenadas en Google y asignación con polígonos preparados.
* Reanudable: cada partición escribe `_SUCCESS.json` con el SHA-256 del archivo de entrada; si coincide con el
  del manifiesto de descarga, la partición no se vuelve a procesar (`--force` la repite).

## Resultados (13/11/2026)

Corrida completa en **194 s** con 4 procesos (la celda `8e3`, 6.8 M de filas, tomó 134 s). Controles:
**12 OK, 1 AVISO, 0 FALLA** (detalle en `docs/calidad/etl_buildings_report.md`).

| | Microsoft | Google |
|---|---:|---:|
| Registros leídos | 4 595 615 | 31 499 115 |
| Fuera de PDET (descartados) | 2 834 572 | 28 804 333 |
| Reparados con `make_valid` | 28 | 0 |
| Multiparte reducidos a su polígono mayor | 22 | 11 |
| Rechazados | 0 | 0 |
| **Edificios escritos** | **1 761 043** | **2 694 782** |
| Municipios PDET con edificios | 170 / 170 | 165 / 170 |
| Duplicados exactos de geometría | 0 | 0 |
| Archivos Parquet / tamaño | 125 particiones, 127 MB | 8 particiones, 222 MB |

Hallazgos:

* **Google no tiene edificios en 5 municipios PDET:** `05475` Murindó, `05873` Vigía del Fuerte, `27099` Bojayá,
  `27450` Medio San Juan y `27491` Nóvita (Atrato y San Juan, en Antioquia y Chocó). No es un efecto del
  prefiltro: se recorrieron las celdas `8e3` y `8e5` completas sin prefiltro y hay 52 167 edificios alrededor de
  esos municipios pero ninguno dentro. Microsoft sí tiene entre 1 331 y 2 004 edificios en cada uno. Es un hueco
  de cobertura de Google v3 que hay que tener en cuenta al comparar fuentes (el único AVISO del reporte).
* **El área de Google difiere de forma casi constante del área en EPSG:9377:** mediana absoluta 0.39 %, p95
  0.54 %, media con signo −0.37 %. Una diferencia tan estable (y no dispersa) indica un cambio de escala por el
  método de cálculo, no geometrías distintas: en una muestra de 5 000 edificios de la celda `8e1`, el área
  geodésica (elipsoide WGS84) también queda −0.44 % por debajo de `area_in_meters`. Por eso se conserva
  `area_in_meters` como define el esquema y la diferencia se documenta.
* La calidad geométrica de ambas fuentes es alta: solo 28 geometrías inválidas en Microsoft (todas reparables) y
  ninguna en Google; ningún edificio colapsó al redondear a 6 decimales.
* El 62 % de los registros de Microsoft y el 91 % de los de Google quedan fuera de PDET: las particiones cubren
  zonas mucho más grandes que los municipios, lo que confirma el valor del prefiltro.

## Contrato de salida (para la carga a MongoDB)

`data/processed/buildings/<fuente>/<partición>/part-NNNNN.parquet` (ignorado por git), GeoParquet 1.0, EPSG:4326.
Cada carpeta de partición tiene además `_SUCCESS.json` con sus conteos; los lectores de Parquet ignoran los
archivos que empiezan por `_`.

| Campo | Tipo | Microsoft | Google | Descripción |
|---|---|:---:|:---:|---|
| `geometry` | Polygon (WKB) | ✓ | ✓ | Huella en WGS84, válida, 6 decimales, exterior antihorario. |
| `area_m2` | double | ✓ | ✓ | Microsoft: área en EPSG:9377. Google: `area_in_meters` original. |
| `confidence` | double | | ✓ | Confianza del modelo de Google (0 a 1). |
| `full_plus_code` | string | | ✓ | Plus Code de Google. |
| `municipality_code` | string (5) | ✓ | ✓ | Código DIVIPOLA del municipio PDET (`municipalities._id`). |
| `source_file` | string | ✓ | ✓ | Archivo de origen (quadkey o celda S2). |
| `is_valid_geom` | bool | ✓ | ✓ | `false` si la geometría original era inválida y se reparó. |

Lectura por lotes para `insert_many`, sin cargar la partición completa:

```python
from buildings_etl import iter_documents

for docs in iter_documents("data/processed/buildings/google/8e3"):   # un lote por row group (50 000)
    collection.insert_many(docs, ordered=False)
```

Cada documento ya tiene la forma de la colección (`geometry` como GeoJSON). Para `ingestion_log`, el SHA-256 del
archivo de origen está en `_SUCCESS.json` (`sha256_entrada`) y en `docs/calidad/manifest_buildings.json`.
