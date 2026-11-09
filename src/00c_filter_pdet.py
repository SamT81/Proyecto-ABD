#!/usr/bin/env python3
"""Filtra la capa municipal del MGN2025 a los 170 municipios PDET y ejecuta los controles de calidad.

Uso:
    python src/00c_filter_pdet.py

Entradas:  shapefile extraído por 00a_download_mgn.py y config/pdet/pdet_municipios.csv (00b).
Salidas:   data/mgn_pdet_2025.gpkg (entrada del ETL 01_load_municipalities.py) y el reporte de
           calidad en docs/calidad/qc_mgn_pdet.{json,md}.
Termina con código 1 si algún control queda en FALLA; los AVISO se documentan pero no detienen.
"""
import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mgn_acquisition import (  # noqa: E402
    FALLA, QCReport, check_catalog, check_mgn_layer, check_pdet_layer, join_catalog,
    load_config, lower_columns, now_iso, repo_path, sha256_file, write_json,
)

OUT_COLUMNS = ["mpio_cdpmp", "mpio_cnmbr", "dpto_ccdgo", "mpio_ccdgo", "dpto_cnmbr", "mpio_tipo",
               "mpio_narea", "pdet_subregion_id", "pdet_subregion", "mgn_version", "geometry"]


def check_source_against_manifest(shp, manifest_path, qc):
    """El filtro solo corre sobre archivos que pasaron por la verificación de 00a."""
    if not manifest_path.exists():
        qc.add("SRC-01", "Manifiesto de descarga disponible", FALLA,
               f"no existe {manifest_path.name}; ejecute src/00a_download_mgn.py")
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qc.expect("SRC-01", "SHA-256 del ZIP verificado en la descarga",
              manifest.get("sha256") == manifest.get("sha256_esperado"), manifest.get("sha256", ""))
    known = {f["name"]: f["sha256"] for f in manifest.get("archivos_extraidos", [])}
    stem = shp.stem
    parts = sorted(p for p in shp.parent.iterdir() if p.stem == stem or p.name.startswith(stem + "."))
    changed = [p.name for p in parts if known.get(p.name) != sha256_file(p)]
    qc.expect("SRC-02", "Archivos extraídos sin cambios desde la descarga", not changed,
              f"modificados: {changed}" if changed else f"{len(parts)} archivos coinciden con el manifiesto")
    return manifest


def subregion_table(sub):
    t = (sub.groupby(["pdet_subregion_id", "pdet_subregion"])
            .agg(municipios=("mpio_cdpmp", "size"), area_km2=("area_km2_calc", "sum"))
            .reset_index())
    return t


def write_markdown(path, qc, meta, table):
    s = qc.summary()
    lines = [
        "# Controles de calidad: MGN2025 nivel municipio filtrado a municipios PDET",
        "",
        f"Generado por `src/00c_filter_pdet.py` el {meta['generado_utc']}.",
        "",
        "| Elemento | Valor |",
        "|---|---|",
        f"| Fuente | {meta['fuente_url']} |",
        f"| SHA-256 del ZIP | `{meta['fuente_sha256']}` |",
        f"| Capa leída | `{meta['capa']}` ({meta['mgn_unidades']} unidades, {meta['crs']}) |",
        f"| Listado PDET | `{meta['catalogo']}` (SHA-256 `{meta['catalogo_sha256'][:16]}...`) |",
        f"| Salida | `{meta['salida']}` (capa `{meta['capa_salida']}`, {meta['salida_municipios']} municipios) |",
        f"| SHA-256 de la salida | `{meta['salida_sha256']}` |",
        f"| Resultado | {s['OK']} OK, {s['AVISO']} AVISO, {s['FALLA']} FALLA |",
        "",
        "## Controles",
        "",
        "| Id | Control | Resultado | Detalle |",
        "|---|---|---|---|",
    ]
    for c in qc.checks:
        det = str(c["detalle"]).replace("|", "/")
        lines.append(f"| {c['id']} | {c['control']} | {c['resultado']} | {det} |")
    lines += ["", "## Municipios y área por subregión PDET", "",
              "| # | Subregión | Municipios | Área (km²) |", "|---|---|---|---|"]
    for r in table.itertuples():
        lines.append(f"| {r.pdet_subregion_id} | {r.pdet_subregion} | {r.municipios} | {r.area_km2:,.1f} |")
    lines.append(f"| | **Total** | **{table['municipios'].sum()}** | **{table['area_km2'].sum():,.1f}** |")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    args = ap.parse_args()

    cfg = load_config(args.config)
    m, out = cfg["mgn"], cfg["output"]
    shp = repo_path(m["extract_dir"]) / m["shapefile"]
    cat_path = repo_path(cfg["pdet"]["catalog_csv"])
    qc = QCReport()

    manifest = check_source_against_manifest(shp, repo_path(out["manifest"]), qc)
    if qc.failed:
        raise SystemExit("[FALLA] la fuente no está verificada")

    print(f"\nLeyendo {shp.name}")
    mgn = lower_columns(gpd.read_file(shp))
    check_mgn_layer(mgn, qc, m["expected_crs"], m.get("expected_municipalities"), cfg["qc"]["bbox"])

    cat = pd.read_csv(cat_path, dtype=str)
    cat["pdet_subregion_id"] = cat["pdet_subregion_id"].astype(int)
    check_catalog(cat, qc, cfg["pdet"]["expected_municipalities"], cfg["pdet"]["expected_subregions"])
    if qc.failed:
        raise SystemExit("[FALLA] la capa o el listado PDET no pasaron los controles básicos")

    sub = join_catalog(mgn, cat, qc)
    sub = gpd.GeoDataFrame(sub, geometry="geometry", crs=mgn.crs)
    sub["mgn_version"] = m["version"]
    sub, _ = check_pdet_layer(sub, qc, cfg)

    gpkg = repo_path(out["gpkg"])
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    if gpkg.exists():
        gpkg.unlink()          # se regenera completo en cada corrida
    result = sub[OUT_COLUMNS].sort_values("mpio_cdpmp").reset_index(drop=True)
    result.to_file(gpkg, layer=out["layer"], driver="GPKG")

    back = gpd.read_file(gpkg, layer=out["layer"])
    qc.expect("OUT-01", "GeoPackage releído con los mismos municipios",
              len(back) == len(result) and set(back["mpio_cdpmp"]) == set(result["mpio_cdpmp"]),
              f"{len(back)} registros")
    qc.expect("OUT-02", "CRS de la salida", back.crs.to_epsg() == 4326, f"EPSG:{back.crs.to_epsg()}")
    nulls = int(back[OUT_COLUMNS[:-1]].isna().sum().sum())
    qc.expect("OUT-03", "Salida sin atributos nulos", nulls == 0, f"{nulls} nulos")

    table = subregion_table(sub)
    meta = {
        "generado_utc": now_iso(),
        "fuente_url": m["url"],
        "fuente_sha256": manifest.get("sha256") if manifest else None,
        "capa": m["shapefile"],
        "mgn_unidades": len(mgn),
        "crs": f"EPSG:{mgn.crs.to_epsg()}",
        "catalogo": cfg["pdet"]["catalog_csv"],
        "catalogo_sha256": sha256_file(cat_path),
        "salida": out["gpkg"],
        "capa_salida": out["layer"],
        "salida_municipios": len(result),
        "salida_sha256": sha256_file(gpkg),
    }
    report = {**meta, "resumen": qc.summary(), "controles": qc.checks,
              "subregiones": table.round(2).to_dict("records")}
    write_json(repo_path(out["qc_json"]), report)
    write_markdown(repo_path(out["qc_md"]), qc, meta, table)

    s = qc.summary()
    print(f"\n{len(result)} municipios PDET -> {out['gpkg']}")
    print(f"Controles: {s['OK']} OK, {s['AVISO']} AVISO, {s['FALLA']} FALLA. Reporte: {out['qc_md']}")
    if qc.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
