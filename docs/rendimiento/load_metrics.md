# Rendimiento de la carga de edificios

Procesos: 4 · lote: 20000 · 2026-11-15T22:01:13+00:00 → 2026-11-15T22:04:59+00:00

| Fuente | Particiones | Documentos | Segundos | Docs/s | Índices (s) |
|---|---:|---:|---:|---:|---|
| microsoft | 125 | 1,761,043 | 82.1 | 21,458.1 | geometry_2dsphere: 23.6, municipality_area: 5.87, source_file_1: 5.07 |
| google | 8 | 2,694,782 | 38.7 | 69,604.0 | geometry_2dsphere: 35.69, municipality_area: 9.6, source_file_1: 7.11, confidence_1: 8.45 |

Verificación microsoft: esperado 1,761,043, en MongoDB 1,761,043, municipios con diferencia 0 → OK

Verificación google: esperado 2,694,782, en MongoDB 2,694,782, municipios con diferencia 0 → OK

## Tamaño de lote (google/8e9, 100,000 documentos)

| Lote | Segundos | Docs/s |
|---:|---:|---:|
| 5000 | 1.0 | 100,050.8 |
| 20000 | 0.76 | 131,246.4 |
| 50000 | 0.77 | 130,513.3 |
