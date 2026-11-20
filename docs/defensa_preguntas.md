# Preguntas probables de la defensa (cada integrante debe poder responderlas)

Se sortean 2 personas: cualquiera puede recibir preguntas de cualquier parte. Las respuestas son guías; se deben dominar con los números finales del informe.

## Diseño y datos
1. **¿Por qué MongoDB y no PostgreSQL/PostGIS?** Documentos con geometría GeoJSON, índice `2dsphere`, `$geoIntersects`/`$geoWithin`/`$near`, agregaciones y carga por lotes sin esquema rígido; el proyecto no necesita joins complejos (el municipio se asigna en el ETL).
2. **¿Por qué una colección por fuente y por qué `municipality_code` en cada edificio?** Los atributos difieren (`confidence` solo en Google), se recarga una sin afectar la otra, y la asignación previa evita un join espacial en cada agregación.
3. **¿Cómo se asignó el municipio a un edificio que cruza un límite?** Con su punto representativo (`point_on_surface`, siempre dentro del polígono): cada edificio queda en un solo municipio, sin doble conteo.
4. **¿Por qué EPSG:4326 para guardar y EPSG:9377 para medir?** `2dsphere` exige lon/lat WGS84; las áreas se calculan en un sistema proyectado de Colombia (MAGNA-SIRGAS Origen Nacional).

## Adquisición y ETL
5. **¿Cómo se verificó la descarga?** Tamaño, MD5 publicado por la fuente, SHA-256 propio, integridad de gzip y manifiesto en `docs/calidad/manifest_buildings.json`; se descargó solo lo que toca PDET (125 quadkeys y 8 celdas S2).
6. **¿Qué pasa con las geometrías inválidas?** `make_valid`, y si quedan varias partes se conserva el polígono mayor; `is_valid_geom` queda en `false` (28 en Microsoft, 0 en Google).
7. **¿Por qué hay 2 694 782 edificios de Google y 1 761 043 de Microsoft, y por qué no se suman?** Google detecta más construcciones pequeñas; las fuentes se solapan (71 % en la muestra), así que sumarlas cuenta dos veces los mismos techos.
8. **¿Por qué Google no tiene edificios en 5 municipios?** Hueco de cobertura verificado recorriendo las celdas completas sin prefiltro (Murindó y Vigía del Fuerte en Antioquia; Bojayá, Medio San Juan y Nóvita en Chocó).

## Carga e índices
9. **¿Qué técnicas hacen eficiente la carga?** Lectura por row groups, `insert_many(ordered=False)` en lotes de 20 000 documentos (131 246 docs/s en benchmark), 4 procesos en paralelo por partición (82.1 s en Microsoft y 38.7 s en Google), índices creados después de la carga, y reanudación por partición con `ingestion_log` y SHA-256.
10. **¿Cómo se sabe que no se perdió ni se duplicó nada?** Los conteos de MongoDB coinciden con los del ETL (total y por municipio); repetir la carga omite las particiones ya cargadas.
11. **¿Qué demuestra el `explain()`?** La consulta de un punto usa `IXSCAN` y examina 5 y 8 documentos; sin índice (`COLLSCAN`) recorre 1.76 y 2.69 millones (7.3 s y 12.5 s frente a 2 ms).
12. **¿Por qué crear los índices después de la carga?** Mantener un índice geoespacial durante millones de inserciones es mucho más lento que construirlo una vez sobre la colección completa.

## Resultados y análisis
13. **¿Cuál es el criterio de techo apto y por qué?** Área ≥ 15 m² y, en Google, confianza ≥ 0.70; es un supuesto parametrizable, guardado con cada resultado, y por eso se hizo un análisis de sensibilidad.
14. **¿Cómo se construyó `results`?** Una agregación `$group` por `municipality_code` y `$merge` con índice único (municipio, fuente); repetirlo reemplaza, no duplica.
15. **¿Qué tan parecidas son las fuentes?** Ver correlaciones y concordancia del ranking de la Sección 5; Google tiene más edificios pero más pequeños.
16. **¿Qué limitaciones tiene el resultado?** La huella no es el área instalable (sin inclinación, orientación ni sombreado); fechas de captura distintas; cobertura desigual; sesgo de 0.37 % en el área de Google.
17. **¿Qué recomendaría a la UPME?** Usar un rango entre escenarios, priorizar los municipios con más área apta y verificar en campo los de mayor discrepancia entre fuentes.

## Proceso del equipo
18. **¿Quién hizo qué?** Adquisición (Carlos), ETL (Alejandro), carga (Sam), índices y EDA (Juan); en la Entrega 4: results (Sam), comparación (Juan), mapas (Carlos), informe final y README (Alejandro). Todos tienen commits propios.
