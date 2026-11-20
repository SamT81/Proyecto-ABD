# Potencial solar de techos en municipios PDET (UPME)

Proyecto final de Administración de Bases de Datos, Pontificia Universidad Javeriana.

**Autores:** Samuel Tovar, Juan Romero, Carlos Pinzón Caicedo y Alejandro Padilla Gaviria.  
**Repositorio:** https://github.com/SamT81/Proyecto-ABD

Estima el número de edificaciones y el área de techos aptos para paneles solares en los 170 municipios PDET de Colombia, utilizando MongoDB y dos datasets abiertos (Microsoft Building Footprints y Google Open Buildings).

## Estado de las entregas

| Semana | Entrega | Estado |
|---|---|---|
| 1 | Esquema NoSQL y plan de implementación | Completada (`docs/Project_Phase1_Report.pdf`) |
| 2 | Fronteras PDET (DANE MGN 2025) e integración espacial NoSQL | Completada (`docs/informe 2/Project_Phase2_Report.pdf`) |
| 3 | Carga de huellas de edificios + EDA | Completada (`docs/informe 3/`) |
| 4 | Resultados, comparación de fuentes, mapas e informe final | Completada (`docs/informe 4/Project_Phase4_Report.pdf`) |

## Estructura del repositorio

```text
docs/
├── informe 2/  Project_Phase2_Report.pdf y fuente LaTeX (Entrega 2)
├── calidad/    Bitácora QA/QC (qc_mgn_pdet.md, manifest_mgn.json, etl_integrity_report.json)
├── evidencia/  Pruebas de índices 2dsphere y planes de ejecución explain() (Entrega 2)
├── evidencia_edificios/  Evidencia de índices de las colecciones de edificios (Entrega 3)
├── eda/        EDA de las huellas (tablas y figuras)
├── rendimiento/  Métricas de la carga a MongoDB
├── resultados/ Colección results exportada (results.csv) y sensibilidad
├── comparacion/  Comparación Microsoft vs Google
├── mapas/      Mapas coropléticos y gráficos
├── informe 3/  Informe de la Entrega 3
├── informe 4/  Informe final (Entrega 4)
├── recursos/   Recursos gráficos (logo_javeriana.png)
└── latex/      Fuente LaTeX y diagrama E-R (Entrega 1)
config/         Parámetros declarativos (params.yaml, spatial.yaml, buildings*.yaml, results.yaml, comparison.yaml, maps.yaml)
src/            Scripts numerados del pipeline e infraestructura de validación
└── utils/      Módulo geo_integrity.py (reparación topológica y proyecciones)
data/           Datos descargados e intermedios (ignorado por git)
notebooks/      Exploración de datos (EDA)
docker-compose.yml
requirements.txt
```

## Cómo levantar la base de datos

```bash
docker compose up -d                        # MongoDB en localhost:27017
docker compose --profile tools up -d        # opcional: mongo-express en localhost:8081
```

## Pipeline de ejecución

### Entrega 2 (Completada)
```bash
python src/00a_download_mgn.py              # Descarga y verificación SHA-256 del MGN 2025 (DANE)
python src/00b_build_pdet_catalog.py        # Extracción del listado oficial ART 170 PDET
python src/00c_filter_pdet.py               # Filtro DIVIPOLA 5 dígitos + 32 controles de calidad
python src/01_load_municipalities.py        # ETL de integridad geométrica y exportación GeoJSON
python src/load_to_mongo.py                # Ingesta NoSQL idempotente e indexación 2dsphere
python src/spatial_evidence.py             # Generación de evidencias con explain("executionStats")
```

### Entrega 3: huellas de edificios
```bash
python src/00d_select_building_partitions.py  # Quadkeys (Microsoft) y celdas S2 (Google) que tocan PDET
python src/00e_download_buildings.py          # Descarga en paralelo con verificación MD5, tamaño y gzip
python src/01b_etl_buildings.py               # ETL: limpieza, municipio PDET, área y GeoParquet por partición
```

```bash
python src/02_load_buildings.py               # Carga a MongoDB por partición (paralela, reanudable), índices y verificación
python src/02_load_buildings.py --benchmark google   # Efecto del tamaño de lote (opcional)
python src/buildings_evidence.py              # Evidencia de índices con explain() y validación cruzada
python src/buildings_eda.py --overlap         # EDA de las huellas de edificios
```

### Entrega 4: resultados, comparación y mapas
```bash
python src/03_build_results.py                # Colección results ($merge), sensibilidad y docs/resultados/results.csv
python src/04_compare_sources.py              # Comparación Microsoft vs Google (docs/comparacion/)
python src/05_make_maps.py                    # Mapas y gráficos (docs/mapas/); requiere data/processed/pdet_municipios.geojson
```

### Reproducir todo desde cero
```bash
pip install -r requirements.txt -r requirements-analysis.txt -r requirements-eda.txt
docker compose up -d                          # MongoDB 7 (Docker con al menos 6 GB de memoria)
python src/00a_download_mgn.py && python src/00b_build_pdet_catalog.py && python src/00c_filter_pdet.py
python src/01_load_municipalities.py && python src/load_to_mongo.py
python src/00d_select_building_partitions.py && python src/00e_download_buildings.py
python src/01b_etl_buildings.py
python src/02_load_buildings.py
python src/buildings_evidence.py && python src/buildings_eda.py --overlap
python src/03_build_results.py && python src/04_compare_sources.py && python src/05_make_maps.py
python -m pytest tests -q
```

## Compilación de informes

### Entrega 1
```bash
cd docs/latex
pdflatex main.tex && pdflatex main.tex
```

### Entrega 2
```bash
cd "docs/informe 2"
pdflatex Project_Phase2_Report.tex && pdflatex Project_Phase2_Report.tex
```

### Entrega 3
Las secciones individuales están versionadas en `docs/informe 3/secciones/` (`adquisicion_edificios.tex`, `etl_edificios.tex`, `carga_edificios.tex` e `indices_eda_edificios.tex`).

### Entrega 4
```bash
cd "docs/informe 4"
pdflatex Project_Phase4_Report.tex && pdflatex Project_Phase4_Report.tex
```

## Fuentes y licencias

Se documentan URL, fecha de descarga y checksum de cada fuente. Se respeta la atribución exigida por las licencias (ODbL, CC BY 4.0).

| Fuente | Archivo | Descarga | SHA-256 |
|---|---|---|---|
| DANE, MGN2025 nivel municipio | [`MGN2025_MPIO_GRAFICO.zip`](https://geoportal.dane.gov.co/descargas/mgn_2025/MGN2025_MPIO_GRAFICO.zip) (71.6 MB) | 08/11/2026 | `a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f` |
| ART, municipios PDET (Decreto 893 de 2017) | `config/pdet/MunicipiosPDET.xlsx` | versionado | ver `docs/calidad/qc_mgn_pdet.md` |
| Microsoft Building Footprints (ODbL) | 125 quadkeys de Colombia que tocan PDET (373 MB) | 13/11/2026 | MD5 y SHA-256 por archivo en `docs/calidad/manifest_buildings.json` |
| Google Open Buildings v3 (CC BY 4.0 y ODbL) | 8 celdas S2 de nivel 4 que tocan PDET (3.1 GB) | 13/11/2026 | MD5 y SHA-256 por archivo en `docs/calidad/manifest_buildings.json` |

Detalle de la descarga y de los controles de calidad: `docs/calidad/qc_mgn_pdet.md` y `docs/adquisicion_mgn.md`
(MGN y PDET), `docs/calidad/qc_buildings_acquisition.md` y `docs/adquisicion_edificios.md` (edificios).
El ETL de edificios y su contrato de salida para la carga están en `docs/etl_edificios.md`.
