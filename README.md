# Potencial solar de techos en municipios PDET (UPME)

Proyecto final de Administración de Bases de Datos, Pontificia Universidad Javeriana.

**Autores:** Samuel Tovar, Juan Romero, Carlos Pinzón Caicedo y Alejandro Padilla Gaviria.
**Repositorio:** https://github.com/SamT81/Proyecto-ABD

Estima el número de edificaciones y el área de techos aptos para paneles solares en los municipios
PDET, usando MongoDB y dos datasets abiertos (Microsoft Building Footprints y Google Open Buildings).

## Estado de las entregas

| Semana | Entrega | Estado |
|---|---|---|
| 1 | Esquema NoSQL y plan de implementación | Entregada (`docs/Project_Phase1_Report.pdf`) |
| 2 | Fronteras PDET (DANE MGN 2025) | Pendiente |
| 3 | Carga de huellas de edificios + EDA | Pendiente |
| 4 | Análisis, mapas e informe final | Pendiente |

## Estructura

```
docs/            informes de cada entrega (PDF), fuente LaTeX (docs/latex/) y diagrama E-R
config/          params.yaml (rutas, CRS, umbrales)
src/             scripts numerados del pipeline
data/            datos descargados (ignorado por git)
notebooks/       EDA
docker-compose.yml
```

## Cómo levantar la base de datos

```bash
docker compose up -d                       # MongoDB en localhost:27017
docker compose --profile tools up -d       # opcional: mongo-express en localhost:8081
```

## Pipeline (se completa en las entregas 2 a 4)

```bash
python src/00a_download_mgn.py             # Entrega 2: descarga y verificación SHA-256 del MGN
python src/00b_build_pdet_catalog.py       # Entrega 2: listado PDET (ART) -> CSV (ya versionado)
python src/00c_filter_pdet.py              # Entrega 2: filtro de los 170 PDET + controles de calidad
python src/01_load_municipalities.py       # Entrega 2
python src/02_load_buildings.py            # Entrega 3
python src/03_compute_results.py           # Entrega 4
python src/04_make_maps.py                 # Entrega 4
```

## Compilar el informe de la Entrega 1

```bash
cd docs/latex
xelatex main.tex && xelatex main.tex       # o pdflatex; también funciona en Overleaf
```

## Fuentes y licencias

Se documentan URL, fecha de descarga y checksum de cada fuente. Se respeta la atribución exigida por
las licencias (ODbL, CC BY 4.0).

| Fuente | Archivo | Descarga | SHA-256 |
|---|---|---|---|
| DANE, MGN2025 nivel municipio | [`MGN2025_MPIO_GRAFICO.zip`](https://geoportal.dane.gov.co/descargas/mgn_2025/MGN2025_MPIO_GRAFICO.zip) (71.6 MB) | 08/11/2026 | `a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f` |
| ART, municipios PDET (Decreto 893 de 2017) | `config/pdet/MunicipiosPDET.xlsx` | versionado | ver `docs/calidad/qc_mgn_pdet.md` |

Detalle de la descarga y de los controles de calidad: `docs/adquisicion_mgn.md`.
