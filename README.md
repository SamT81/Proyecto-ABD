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
| 3 | Carga de huellas de edificios + EDA | Pendiente |
| 4 | Análisis, mapas e informe final | Pendiente |

## Estructura del repositorio

```text
docs/
├── informe 2/  Project_Phase2_Report.pdf y fuente LaTeX (Entrega 2)
├── calidad/    Bitácora QA/QC (qc_mgn_pdet.md, manifest_mgn.json, etl_integrity_report.json)
├── evidencia/  Pruebas de índices 2dsphere y planes de ejecución explain()
├── recursos/   Recursos gráficos (logo_javeriana.png)
└── latex/      Fuente LaTeX y diagrama E-R (Entrega 1)
config/         Parámetros declarativos (acquisition.yaml, params.yaml, spatial.yaml)
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

### Entregas futuras
```bash
python src/02_load_buildings.py            # Entrega 3: Carga de huellas de edificios
python src/03_compute_results.py           # Entrega 4: Cálculo de potencial solar
python src/04_make_maps.py                 # Entrega 4: Generación de cartografía final
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

## Fuentes y licencias

Se documentan URL, fecha de descarga y checksum de cada fuente. Se respeta la atribución exigida por las licencias (ODbL, CC BY 4.0).

| Fuente | Archivo | Descarga | SHA-256 |
|---|---|---|---|
| DANE, MGN2025 nivel municipio | [`MGN2025_MPIO_GRAFICO.zip`](https://geoportal.dane.gov.co/descargas/mgn_2025/MGN2025_MPIO_GRAFICO.zip) (71.6 MB) | 08/11/2026 | `a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f` |
| ART, municipios PDET (Decreto 893 de 2017) | `config/pdet/MunicipiosPDET.xlsx` | versionado | ver `docs/calidad/qc_mgn_pdet.md` |

Detalle de la descarga y de los controles de calidad: `docs/calidad/qc_mgn_pdet.md` y `docs/adquisicion_mgn.md`.
