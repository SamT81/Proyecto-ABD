# Controles de calidad: adquisición de huellas de edificios

Generado por `src/00d_select_building_partitions.py` y `src/00e_download_buildings.py`.

## Selección de particiones (00d)

Corrida: 2026-11-13T22:32:17+00:00. Resultado: **10 OK, 0 AVISO, 0 FALLA**.

| Id | Control | Resultado | Detalle |
|---|---|---|---|
| SEL-01 | Municipios PDET de entrada | OK | 170 (esperados 170), EPSG:4326 |
| SEL-02 | Particiones de Microsoft para Colombia | OK | 232 quadkeys de nivel 9 en el índice (subido 2026-02-23) |
| SEL-03 | Un archivo por quadkey en el índice | OK | 0 quadkeys repetidos |
| SEL-04 | Quadkeys de Microsoft que tocan PDET | OK | 125 de 232 (~373.1 MB de ~678.7 MB del país) |
| SEL-05 | Municipios PDET cubiertos por particiones de Microsoft | OK | 170/170 |
| SEL-06 | Objetos del bucket de Google = celdas de tiles.geojson | OK | 333 objetos / 333 celdas S2 |
| SEL-07 | Celdas seleccionadas con archivo en el bucket | OK | todas tienen tamaño y MD5 publicados |
| SEL-08 | Tamaño en tiles.geojson = tamaño en el bucket | OK | 8 celdas coinciden |
| SEL-09 | Celdas S2 de Google que tocan PDET | OK | 8 de 333 (3,110.1 MB de 178.3 GB) |
| SEL-10 | Municipios PDET cubiertos por particiones de Google | OK | 170/170 |

## Descarga y verificación (00e)

Corrida: 2026-11-13T22:36:55+00:00. Resultado: **14 OK, 0 AVISO, 0 FALLA**.

| Id | Control | Resultado | Detalle |
|---|---|---|---|
| DL-M1 | Archivos de microsoft disponibles | OK | 125/125 |
| DL-M2 | Tamaño = Content-Length del servidor (microsoft) | OK | 125/125 verificados |
| DL-M3 | Tamaño = tamaño publicado en el índice (microsoft) | OK | 125/125 verificados |
| DL-M4 | MD5 = valor oficial de la fuente (microsoft) | OK | 95/95 verificados |
| DL-M5 | Integridad gzip (descompresión completa) (microsoft) | OK | 125/125 verificados |
| DL-M6 | Formato de la primera línea (microsoft) | OK | 125/125 verificados |
| DL-M7 | Registros en los archivos de microsoft | OK | 4,595,615 registros en 373.4 MB |
| DL-G1 | Archivos de google disponibles | OK | 8/8 |
| DL-G2 | Tamaño = Content-Length del servidor (google) | OK | 8/8 verificados |
| DL-G3 | Tamaño = tamaño publicado en el índice (google) | OK | 8/8 verificados |
| DL-G4 | MD5 = valor oficial de la fuente (google) | OK | 8/8 verificados |
| DL-G5 | Integridad gzip (descompresión completa) (google) | OK | 8/8 verificados |
| DL-G6 | Formato de la primera línea (google) | OK | 8/8 verificados |
| DL-G7 | Registros en los archivos de google | OK | 31,499,115 registros en 3,110.1 MB |
