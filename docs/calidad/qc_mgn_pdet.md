# Controles de calidad: MGN2025 nivel municipio filtrado a municipios PDET

Generado por `src/00c_filter_pdet.py` el 2026-11-09T14:20:53+00:00.

| Elemento | Valor |
|---|---|
| Fuente | https://geoportal.dane.gov.co/descargas/mgn_2025/MGN2025_MPIO_GRAFICO.zip |
| SHA-256 del ZIP | `a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f` |
| Capa leída | `MGN_ADM_MPIO_GRAFICO.shp` (1122 unidades, EPSG:4326) |
| Listado PDET | `config/pdet/pdet_municipios.csv` (SHA-256 `582e2bd9b6ed0bc9...`) |
| Salida | `data/mgn_pdet_2025.gpkg` (capa `municipios_pdet`, 170 municipios) |
| SHA-256 de la salida | `eedd7bf2c0d2e272de6e36d47bd9c007fc740b6f5b1d5705f8c84fb0b2a36637` |
| Resultado | 31 OK, 1 AVISO, 0 FALLA |

## Controles

| Id | Control | Resultado | Detalle |
|---|---|---|---|
| SRC-01 | SHA-256 del ZIP verificado en la descarga | OK | a3c01393059be8f2947de5e0a828faa4c7a43119819a667a8124854340bc141f |
| SRC-02 | Archivos extraídos sin cambios desde la descarga | OK | 8 archivos coinciden con el manifiesto |
| MGN-01 | Campos requeridos presentes en la capa | OK | dpto_ccdgo, mpio_ccdgo, mpio_cdpmp, dpto_cnmbr, mpio_cnmbr, mpio_tipo, mpio_narea |
| MGN-02 | Sistema de referencia de la capa | OK | EPSG:4326 (esperado EPSG:4326) |
| MGN-03 | Unidades en la capa municipal | OK | 1122 (esperadas 1122) |
| MGN-04 | mpio_cdpmp único | OK | 0 duplicados |
| MGN-05 | mpio_cdpmp con 5 dígitos | OK | 0 inválidos |
| MGN-06 | mpio_cdpmp = dpto_ccdgo + mpio_ccdgo | OK | 0 incoherentes |
| MGN-07 | Atributos y geometrías sin nulos | OK | 0 nulos |
| MGN-08 | Extensión dentro de la caja de Colombia | OK | [-81.7356, -4.2294, -66.8472, 13.3947] |
| PDET-01 | Municipios en el listado PDET | OK | 170 (esperados 170) |
| PDET-02 | Códigos DIVIPOLA únicos en el listado | OK | sin duplicados |
| PDET-03 | Códigos con formato de 5 dígitos | OK |  |
| PDET-04 | Subregiones PDET | OK | 16 (esperadas 16) |
| PDET-05 | Prefijo del código municipal = código de departamento | OK |  |
| PDET-06 | Campos sin valores nulos | OK | 0 nulos |
| JOIN-01 | Códigos PDET encontrados en el MGN | OK | 170/170 |
| JOIN-02 | Departamento del listado = departamento del MGN | OK |  |
| JOIN-03 | Nombre del municipio coincide (sin tildes) | AVISO | 19418: MGN 'LÓPEZ DE MICAY' / ART 'LÓPEZ'; 19548: MGN 'PIENDAMÓ - TUNÍA' / ART 'PIENDAMÓ'; 50711: MGN 'VISTAHERMOSA' / ART 'VISTA HERMOSA'; 70523: MGN 'PALMITO' / ART 'SAN ANTONIO DE PALMITO'; 70823: MGN 'SAN JOSÉ DE TOLUVIEJO' / ART 'TOLÚ VIEJO'; 86573: MGN 'PUERTO LEGUÍZAMO' / ART 'LEGUÍZAMO' |
| GEO-01 | Municipios PDET en la capa filtrada | OK | 170 (esperados 170) |
| GEO-02 | Un polígono por código | OK |  |
| GEO-03 | Tipos de geometría Polygon/MultiPolygon | OK | {"Polygon": 168, "MultiPolygon": 2} |
| GEO-04 | Geometrías no vacías | OK | 0 vacías |
| GEO-05 | Geometrías válidas (OGC) | OK | 170 válidas |
| GEO-06 | Área en EPSG:9377 vs mpio_narea del DANE | OK | diferencia máx. 0.000% (52520 FRANCISCO PIZARRO), media 0.000% |
| GEO-07 | Áreas positivas | OK | total PDET 389,182 km² |
| GEO-08 | Sin solapes entre municipios PDET vecinos | OK | 339 pares vecinos revisados |
| GEO-09 | Tamaño de la geometría por documento | OK | máx. 2.20 MB (18756, 51,716 vértices); vértices totales 1,556,026 |
| GEO-10 | Tipo de entidad territorial (mpio_tipo) | OK | {"MUNICIPIO": 170} |
| OUT-01 | GeoPackage releído con los mismos municipios | OK | 170 registros |
| OUT-02 | CRS de la salida | OK | EPSG:4326 |
| OUT-03 | Salida sin atributos nulos | OK | 0 nulos |

## Municipios y área por subregión PDET

| # | Subregión | Municipios | Área (km²) |
|---|---|---|---|
| 1 | ALTO PATÍA Y NORTE DEL CAUCA | 24 | 13,177.8 |
| 2 | ARAUCA | 4 | 10,539.5 |
| 3 | BAJO CAUCA Y NORDESTE ANTIOQUEÑO | 13 | 17,615.2 |
| 4 | CATATUMBO | 8 | 9,237.6 |
| 5 | CHOCÓ | 14 | 29,548.4 |
| 6 | CUENCA DEL CAGUÁN Y PIEDEMONTE CAQUETEÑO | 17 | 93,298.4 |
| 7 | MACARENA - GUAVIARE | 12 | 96,168.8 |
| 8 | MONTES DE MARÍA | 15 | 6,406.9 |
| 9 | PACÍFICO MEDIO | 4 | 14,302.1 |
| 10 | PACÍFICO Y FRONTERA NARIÑENSE | 11 | 17,118.6 |
| 11 | PUTUMAYO | 9 | 25,062.7 |
| 12 | SIERRA NEVADA - PERIJÁ | 15 | 20,414.9 |
| 13 | SUR DE BOLÍVAR | 7 | 10,331.9 |
| 14 | SUR DE CÓRDOBA | 5 | 9,581.2 |
| 15 | SUR DEL TOLIMA | 4 | 6,918.9 |
| 16 | URABÁ ANTIOQUEÑO | 8 | 9,459.3 |
| | **Total** | **170** | **389,182.0** |
