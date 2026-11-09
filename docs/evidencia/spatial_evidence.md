# Evidencia de integración espacial

MongoDB 7.0.45 · base `upme_solar` · colección `municipalities` · 170 documentos · 2026-11-09T14:22:21.932553+00:00

## Índices

- `_id_`: `{'_id': 1}`
- `geometry_2dsphere`: `{'geometry': '2dsphere'}`
- `pdet_subregion_1`: `{'pdet_subregion': 1}`

## Controles

| Control | Resultado | Detalle |
|---|---|---|
| índice 2dsphere en geometry | OK | [{"_id_": {"_id": 1}}, {"geometry_2dsphere": {"geometry": "2dsphere"}}, {"pdet_subregion_1": {"pdet_subregion": 1}}] |
| número de municipios | OK | 170 cargados, 170 esperados |
| número de subregiones PDET | OK | 16 encontradas, 16 esperadas |
| códigos DIVIPOLA de 5 dígitos | OK | 0 inválidos |
| geometrías MultiPolygon | OK | 0 con otro tipo |
| punto_en_poligono[05031]: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=9 docs=1 devueltos=1 |
| punto_en_poligono[13688]: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=9 docs=1 devueltos=1 |
| punto_en_poligono[19548]: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=11 docs=2 devueltos=1 |
| punto_en_poligono[47001]: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=6 docs=1 devueltos=1 |
| punto_en_poligono[54800]: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=9 docs=1 devueltos=1 |
| punto_en_el_oceano: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=0 docs=0 devueltos=0 |
| ventana_geoWithin: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=525 docs=34 devueltos=18 |
| vecinos_geoIntersects: usa índice 2dsphere | OK | etapas=['FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=52 docs=5 devueltos=1 |
| cercanos_near: usa índice 2dsphere | OK | etapas=['GEO_NEAR_2DSPHERE', 'FETCH', 'IXSCAN', 'FETCH', 'IXSCAN', 'FETCH', 'IXSCAN'] índice=geometry_2dsphere claves=388 docs=335 devueltos=18 |

## Municipios por subregión

| Subregión | Municipios |
|---|---|
| ALTO PATÍA Y NORTE DEL CAUCA | 24 |
| ARAUCA | 4 |
| BAJO CAUCA Y NORDESTE ANTIOQUEÑO | 13 |
| CATATUMBO | 8 |
| CHOCÓ | 14 |
| CUENCA DEL CAGUÁN Y PIEDEMONTE CAQUETEÑO | 17 |
| MACARENA - GUAVIARE | 12 |
| MONTES DE MARÍA | 15 |
| PACÍFICO MEDIO | 4 |
| PACÍFICO Y FRONTERA NARIÑENSE | 11 |
| PUTUMAYO | 9 |
| SIERRA NEVADA - PERIJÁ | 15 |
| SUR DE BOLÍVAR | 7 |
| SUR DE CÓRDOBA | 5 |
| SUR DEL TOLIMA | 4 |
| URABÁ ANTIOQUEÑO | 8 |

## Consultas: con índice vs. recorrido completo

| Consulta | Plan | Claves | Docs examinados | Devueltos | ms |
|---|---|---|---|---|---|
| punto_en_poligono[05031] | FETCH/IXSCAN | 9 | 1 | 1 | 4 |
| punto_en_poligono[05031] (sin índice) | COLLSCAN | 0 | 170 | 1 | 316 |
| punto_en_poligono[13688] | FETCH/IXSCAN | 9 | 1 | 1 | 2 |
| punto_en_poligono[13688] (sin índice) | COLLSCAN | 0 | 170 | 1 | 316 |
| punto_en_poligono[19548] | FETCH/IXSCAN | 11 | 2 | 1 | 3 |
| punto_en_poligono[19548] (sin índice) | COLLSCAN | 0 | 170 | 1 | 324 |
| punto_en_poligono[47001] | FETCH/IXSCAN | 6 | 1 | 1 | 6 |
| punto_en_poligono[47001] (sin índice) | COLLSCAN | 0 | 170 | 1 | 308 |
| punto_en_poligono[54800] | FETCH/IXSCAN | 9 | 1 | 1 | 4 |
| punto_en_poligono[54800] (sin índice) | COLLSCAN | 0 | 170 | 1 | 323 |
| punto_en_el_oceano | FETCH/IXSCAN | 0 | 0 | 0 | 0 |
| punto_en_el_oceano (sin índice) | COLLSCAN | 0 | 170 | 0 | 313 |
| ventana_geoWithin | FETCH/IXSCAN | 525 | 34 | 18 | 78 |
| ventana_geoWithin (sin índice) | COLLSCAN | 0 | 170 | 18 | 319 |
| vecinos_geoIntersects | FETCH/IXSCAN | 52 | 5 | 1 | 122 |
| vecinos_geoIntersects (sin índice) | COLLSCAN | 0 | 170 | 1 | 405 |
| cercanos_near | GEO_NEAR_2DSPHERE/FETCH/IXSCAN/FETCH/IXSCAN/FETCH/IXSCAN | 388 | 335 | 18 | 80 |
