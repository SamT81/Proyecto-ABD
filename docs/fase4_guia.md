# Entrega 4: guía del equipo

Entrega: lunes 23 de noviembre de 2026, antes de las 2:00 p. m. (repositorio con commits de todos + PDF en Brightspace). Defensa final: se sortean 2 personas.

| Quién | Rama | Código | Informe |
|---|---|---|---|
| Sam | `feat/results` | `src/03_build_results.py`, `config/results.yaml`, `tests/test_results.py` | `secciones/resultados.tex`, `sensibilidad.tex` |
| Juan | `feat/comparison` | `src/04_compare_sources.py`, `config/comparison.yaml`, `tests/test_comparison.py` | `secciones/comparacion.tex` |
| Carlos | `feat/maps` | `src/05_make_maps.py`, `config/maps.yaml`, `tests/test_maps.py` | `secciones/mapas.tex` |
| Alejandro | `feat/final-report` | `README.md`, `docs/defensa_preguntas.md`, `docs/fase4_guia.md` | `Project_Phase4_Report.tex`, `secciones/discusion.tex`, `conclusiones.tex` |

Las secciones están en `docs/informe 4/secciones/`. Cada `\pend{...}` en rojo se reemplaza con los números reales; no debe quedar ninguno en el PDF final.

## Orden de ejecución
```bash
docker compose up -d
python src/03_build_results.py        # Sam: results + docs/resultados/results.csv + sensibilidad.csv
python src/04_compare_sources.py      # Juan: docs/comparacion/
python src/05_make_maps.py            # Carlos: docs/mapas/ (necesita data/processed/pdet_municipios.geojson o --mongo)
```
`04` y `05` aceptan `--input docs/eda/por_municipio.csv` para empezar antes de tener `results.csv`.

## Verificación previa al cierre
- Compartir `data/processed/pdet_municipios.geojson` por fuera de Git para la generación de mapas (`05_make_maps.py`).
- Verificar que `grep -rn "\\pend{" "docs/informe 4/"` no devuelva coincidencias antes de compilar el PDF final en Overleaf.
- Ejecutar `python -m pytest tests -q` tras integrar todas las ramas en `main`.
