# Comparación Microsoft vs Google

165 de 170 municipios comparables; sin datos de Google: 05475, 05873, 27099, 27450, 27491.

| Fuente | Edificios | Área total (km²) | Techos aptos | Área apta (km²) |
|---|---:|---:|---:|---:|
| microsoft | 1,761,043 | 221.13 | 1,756,529 | 221.07 |
| google | 2,694,782 | 223.01 | 2,161,261 | 206.28 |

Correlación por municipio: conteo_pearson 0.9152, conteo_spearman 0.9038, area_apta_pearson 0.9855, area_apta_spearman 0.9371
Razón Google/Microsoft: conteo_mediana 1.4, area_apta_mediana 0.922, municipios_google_mayor_conteo 133, municipios_google_mayor_area_apta 60, error_relativo_abs_medio_area_apta 0.246
Concordancia del ranking por área apta: 17 de 20 municipios comunes en el top (Spearman de rangos 0.9371).

## Mayores discrepancias en área apta (absolutas)

|   municipality_code | name                   |   ms_building_count |   g_building_count |   ms_apt_km2 |   g_apt_km2 |   diff_apt_km2 |   rel_diff_apt |
|--------------------:|:-----------------------|--------------------:|-------------------:|-------------:|------------:|---------------:|---------------:|
|               18753 | SAN VICENTE DEL CAGUÁN |               23587 |              21599 |        3.756 |       2.411 |         -1.345 |         -0.358 |
|               81736 | SARAVENA               |               16141 |              25140 |        2.962 |       1.848 |         -1.113 |         -0.376 |
|               52835 | SAN ANDRÉS DE TUMACO   |               41424 |              50494 |        4.526 |       3.442 |         -1.084 |         -0.24  |
|               54810 | TIBÚ                   |               35478 |              32843 |        3.568 |       2.499 |         -1.069 |         -0.3   |
|               05837 | TURBO                  |               43359 |              78927 |        4.659 |       5.571 |          0.912 |          0.196 |
|               20001 | VALLEDUPAR             |               63722 |             171425 |       13.509 |      14.363 |          0.854 |          0.063 |
|               19256 | EL TAMBO               |               34366 |              38900 |        3.051 |       2.252 |         -0.799 |         -0.262 |
|               50350 | LA MACARENA            |               12895 |               9900 |        1.788 |       1.006 |         -0.782 |         -0.438 |
|               47001 | SANTA MARTA            |               67664 |             183651 |       14.208 |      14.963 |          0.755 |          0.053 |
|               05031 | AMALFI                 |                6860 |               2983 |        0.868 |       0.168 |         -0.699 |         -0.806 |

## Procedencia y reproducción

Entrada: `docs/resultados/results.csv` de la rama `feat/results`, commit `520fdc6`, generado mediante `src/03_build_results.py` sobre MongoDB 7 local con las colecciones reales. Ambos conteos fueron verificados contra las colecciones originales. La ejecución usó el servidor nativo ya instalado en Windows.

En esta rama se ejecutó `python src/04_compare_sources.py --input data/results_entrega4.csv`, usando una copia idéntica del CSV publicado en `feat/results`. Una vez integrados los resultados en la misma copia del repositorio, se puede ejecutar `python src/04_compare_sources.py` sin argumentos.

Pruebas: 7 de resultados y 6 de comparación aprobadas. En Windows se configuró `PYTHONIOENCODING=utf-8` para la salida de consola y se instaló `scipy` para la correlación de Spearman.
