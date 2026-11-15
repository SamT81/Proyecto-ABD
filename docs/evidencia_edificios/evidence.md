# Evidencia de índices: colecciones de edificios

MongoDB 7.0.48 · base `upme_solar` · 2026-11-15T22:05:06+00:00


## `buildings_microsoft` (1,761,043 documentos)

| Control | Resultado | Detalle |
|---|---|---|
| colección con documentos | OK | 1,761,043 documentos |
| índice 2dsphere en geometry | OK | {"_id_": {"_id": 1}, "geometry_2dsphere": {"geometry": "2dsphere"}, "municipality_area": {"municipality_code": 1, "area_m2": -1}, "source_file_1": {"source_file": 1}} |
| índice compuesto municipality_code+area_m2 | OK |  |
| todas las geometrías son Polygon | OK | 0 con otro tipo |
| todos los edificios tienen municipality_code | OK | 0 sin código |
| códigos de municipio válidos (subconjunto de los 170 PDET) | OK | 170 municipios con edificios; 0 códigos desconocidos |
| punto_en_edificio: usa índice espacial | OK | etapas=['FETCH', 'IXSCAN'] claves=17 docs=5 devueltos=1 |
| cercanos_near: usa índice espacial | OK | etapas=['GEO_NEAR_2DSPHERE', 'FETCH', 'IXSCAN', 'FETCH', 'IXSCAN'] claves=1244 docs=1191 devueltos=462 |
| asignación previa vs $geoWithin | OK | SIPÍ (27745): 653 por código, 651 por $geoWithin (99.7 %); la diferencia son edificios que cruzan el límite |

| Consulta | Plan | Claves | Docs examinados | Devueltos | ms |
|---|---|---|---|---|---|
| punto_en_edificio | FETCH/IXSCAN | 17 | 5 | 1 | 2 |
| punto_en_edificio (sin índice) | COLLSCAN | 0 | 1761043 | 1 | 7336 |
| cercanos_near | GEO_NEAR_2DSPHERE/FETCH/IXSCAN/FETCH/IXSCAN | 1244 | 1191 | 462 | 10 |

## `buildings_google` (2,694,782 documentos)

| Control | Resultado | Detalle |
|---|---|---|
| colección con documentos | OK | 2,694,782 documentos |
| índice 2dsphere en geometry | OK | {"_id_": {"_id": 1}, "geometry_2dsphere": {"geometry": "2dsphere"}, "municipality_area": {"municipality_code": 1, "area_m2": -1}, "source_file_1": {"source_file": 1}, "confidence_1": {"confidence": 1}} |
| índice compuesto municipality_code+area_m2 | OK |  |
| todas las geometrías son Polygon | OK | 0 con otro tipo |
| todos los edificios tienen municipality_code | OK | 0 sin código |
| códigos de municipio válidos (subconjunto de los 170 PDET) | OK | 165 municipios con edificios; 0 códigos desconocidos |
| punto_en_edificio: usa índice espacial | OK | etapas=['FETCH', 'IXSCAN'] claves=22 docs=8 devueltos=1 |
| cercanos_near: usa índice espacial | OK | etapas=['GEO_NEAR_2DSPHERE', 'FETCH', 'IXSCAN', 'FETCH', 'IXSCAN'] claves=870 docs=813 devueltos=270 |
| asignación previa vs $geoWithin | OK | SIPÍ (27745): 1 por código, 1 por $geoWithin (100.0 %); la diferencia son edificios que cruzan el límite |

| Consulta | Plan | Claves | Docs examinados | Devueltos | ms |
|---|---|---|---|---|---|
| punto_en_edificio | FETCH/IXSCAN | 22 | 8 | 1 | 2 |
| punto_en_edificio (sin índice) | COLLSCAN | 0 | 2694782 | 1 | 12464 |
| cercanos_near | GEO_NEAR_2DSPHERE/FETCH/IXSCAN/FETCH/IXSCAN | 870 | 813 | 270 | 14 |
