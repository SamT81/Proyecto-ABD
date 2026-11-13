# Reporte del ETL de huellas de edificios

Generado por `src/01b_etl_buildings.py` el 2026-11-13T22:43:51+00:00 (194.3 s). Detalle por partición en `etl_buildings_report.json`.

## Resumen por fuente

| Fuente | Particiones | Leídos | Fuera de PDET | Reparados | Multiparte reducidos | Rechazados | Escritos | Municipios con edificios | Duplicados exactos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| microsoft | 125 | 4,595,615 | 2,834,572 | 28 | 22 | 0 | 1,761,043 | 170/170 | 0 |
| google | 8 | 31,499,115 | 28,804,333 | 0 | 11 | 0 | 2,694,782 | 165/170 | 0 |

Rechazados por motivo:

* microsoft: ninguno
* google: ninguno

## Área de Google frente a EPSG:9377

Sobre 2,694,782 edificios de Google dentro de PDET, la diferencia relativa entre `area_in_meters` y el área recalculada en EPSG:9377 tiene mediana absoluta de 0.390 %, p95 de 0.544 % y p99 de 0.573 % (media con signo -0.369 %).

## Controles

| Id | Control | Resultado | Detalle |
|---|---|---|---|
| ETL-M1 | Particiones procesadas (microsoft) | OK | 125/125 |
| ETL-M2 | Salida releída: esquema, EPSG:4326, Polygon válidos y códigos PDET (microsoft) | OK | 1,761,043 registros |
| ETL-M3 | Registros releídos = registros escritos (microsoft) | OK | 1,761,043 / 1,761,043 |
| ETL-M4 | Municipios PDET con al menos un edificio (microsoft) | OK | 170/170 |
| ETL-M5 | Geometrías rechazadas (microsoft) | OK | 0 (0.0000 %); reparadas 28, multiparte reducidas 22 |
| ETL-M6 | Sin geometrías duplicadas exactas (microsoft) | OK | 0 duplicadas de 1,761,043 |
| ETL-G1 | Particiones procesadas (google) | OK | 8/8 |
| ETL-G2 | Salida releída: esquema, EPSG:4326, Polygon válidos y códigos PDET (google) | OK | 2,694,782 registros |
| ETL-G3 | Registros releídos = registros escritos (google) | OK | 2,694,782 / 2,694,782 |
| ETL-G4 | Municipios PDET con al menos un edificio (google) | AVISO | 165/170; sin edificios: ['05475', '05873', '27099', '27450', '27491'] |
| ETL-G5 | Geometrías rechazadas (google) | OK | 0 (0.0000 %); reparadas 0, multiparte reducidas 11 |
| ETL-G6 | Sin geometrías duplicadas exactas (google) | OK | 0 duplicadas de 2,694,782 |
| ETL-G7 | area_in_meters de Google coherente con el área en EPSG:9377 | OK | mediana 0.390 %, p95 0.544 % |

## Edificios por municipio (10 con más edificios)

* microsoft: 47001 (67,664), 20001 (63,722), 05837 (43,359), 52835 (41,424), 54810 (35,478), 19256 (34,366), 76109 (33,106), 19698 (30,843), 23807 (30,255), 81065 (27,815)
* google: 47001 (183,651), 20001 (171,425), 76109 (103,888), 05837 (78,927), 18001 (58,135), 52835 (50,494), 23807 (43,123), 47189 (42,068), 19130 (41,281), 19256 (38,900)
