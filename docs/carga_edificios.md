# Entrega 3: carga de edificios a MongoDB, índices y EDA

Lee la salida GeoParquet del ETL (`docs/etl_edificios.md`) y la deja en `buildings_microsoft` y `buildings_google`.

| Archivo | Función |
|---|---|
| `src/02_load_buildings.py` | Carga por partición en paralelo, índices después de la carga, reanudación con `ingestion_log`, verificación y métricas. |
| `config/buildings_load.yaml` | Colecciones, índices, tamaños de lote del benchmark y rutas de salida. |
| `src/buildings_evidence.py` | Evidencia de índices (`explain` con y sin índice) y validación cruzada de `municipality_code`. |
| `src/buildings_eda.py` | EDA con agregaciones de MongoDB: conteos y áreas por municipio, histogramas, techos aptos, solapamiento. |
| `config/buildings_analysis.yaml` | Salidas de evidencia y EDA. |
| `tests/test_buildings_load.py`, `tests/test_buildings_eda.py` | Pruebas con GeoParquet sintético y mongomock (sin MongoDB). |

## Orden de ejecución

```bash
docker compose up -d                                              # MongoDB 7
python src/01_load_municipalities.py                              # municipios (Entrega 2), si la base está vacía
python src/02_load_buildings.py --source all --dry-run --limit-partitions 2
python src/02_load_buildings.py --benchmark google                # tamaños de lote
python src/02_load_buildings.py --source all                      # carga + índices + verificación
python src/buildings_evidence.py                                  # docs/evidencia_edificios/
python src/buildings_eda.py --overlap                             # docs/eda/
```

Si se interrumpe, se vuelve a ejecutar el mismo comando: las particiones ya cargadas se omiten. `--drop` empieza de cero.
Las métricas quedan en `docs/rendimiento/load_metrics.json` y `.md`.
