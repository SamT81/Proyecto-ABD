# Entrega 2: integración espacial NoSQL (MongoDB)

Parte de la Entrega 2 que cubre el criterio **NoSQL Spatial Integration: evidencia de índices espaciales implementados**.

## Qué hace cada archivo

| Archivo | Función |
|---|---|
| `config/spatial.yaml` | Ruta del GeoJSON limpio, caja de Colombia, conteos esperados (170 municipios, 16 subregiones). |
| `src/pdet_mongo.py` | Validación y construcción de documentos `municipalities`; lectura de planes `explain()`. No usa MongoDB. |
| `src/load_to_mongo.py` | Carga idempotente (upsert por `_id`), crea los índices y registra la carga en `ingestion_log`. |
| `src/spatial_evidence.py` | Controles de integridad + consultas espaciales con `explain("executionStats")`, con y sin índice. |
| `docs/evidencia/consultas_mongosh.js` | Las mismas consultas en mongosh, para capturas. |
| `tests/test_pdet_mongo.py` | Pruebas sin base de datos. |

## Contrato de entrada (lo que debe producir el ETL de integridad)

GeoJSON `FeatureCollection` en **EPSG:4326** con un Feature por municipio PDET. Propiedades (se aceptan los
nombres originales del MGN o los del esquema):

| Esquema | Alias aceptados | Obligatorio |
|---|---|---|
| `municipality_code` (DIVIPOLA, 5 dígitos) | `_id`, `MPIO_CDPMP`, `DIVIPOLA` | Sí |
| `name` | `MPIO_CNMBR` | Sí |
| `pdet_subregion` | `subregion` | Sí |
| `department_code`, `department_name` | `DPTO_CCDGO`, `DPTO_CNMBR` | No (el código sale de los 2 primeros dígitos) |
| `area_km2` | | No (si falta se calcula en EPSG:9377) |

Se rechaza (y queda en `ingestion_log`) cualquier feature con código inválido o duplicado, geometría inválida,
vacía o fuera de la caja de Colombia (típico de coordenadas invertidas o en EPSG:9377). Las geometrías se
convierten a `MultiPolygon` y se orientan con la regla de la mano derecha. `--repair` intenta repararlas con
`make_valid`. El script crea los índices **antes** de insertar: MongoDB rechaza toda geometría que no pueda indexar,
lo que sirve de validación adicional.

## Cómo ejecutarlo

```bash
pip install -r requirements.txt pyyaml
docker compose up -d
python src/load_to_mongo.py --dry-run          # valida sin tocar la base
python src/load_to_mongo.py                    # carga + índices + ingestion_log
python src/spatial_evidence.py                 # genera docs/evidencia/*
python -m pytest tests -q
```

`spatial_evidence.py` termina con código 1 si algún control falla y escribe `spatial_evidence.json`,
`spatial_evidence.md` y `spatial_evidence_table.tex` en `docs/evidencia/`.
