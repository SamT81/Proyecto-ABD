#!/usr/bin/env python3
"""Selecciona las particiones de Microsoft y Google que intersectan los municipios PDET.

Uso:
    python src/00d_select_building_partitions.py              # usa los índices de data/raw si ya existen
    python src/00d_select_building_partitions.py --refresh    # vuelve a bajar los índices de las fuentes

Entradas: índice de Microsoft (dataset-links.csv), teselas S2 de Google (tiles.geojson), listado del
bucket de Google (tamaño y MD5 de cada objeto) y los 170 polígonos PDET de la Entrega 2. Salida:
config/buildings/particiones_pdet.csv, que es la lista exacta de archivos que descarga 00e.
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildings_acquisition as ba  # noqa: E402


def fetch(url, dest, refresh):
    if dest.exists() and not refresh:
        return False
    print(f"Descargando índice {url}")
    ba.download(url, dest)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--refresh", action="store_true", help="vuelve a descargar los índices de las fuentes")
    args = ap.parse_args()

    cfg = ba.load_buildings_config(args.config)
    ms, gg = cfg["sources"]["microsoft"], cfg["sources"]["google"]
    buffer_deg = float(cfg["selection"]["buffer_deg"])
    qc = ba.QCReport()

    pdet_path = ba.repo_path(cfg["pdet"]["gpkg"])
    if not pdet_path.exists():
        raise SystemExit(f"[FALLA] no existe {pdet_path}; ejecute antes src/00c_filter_pdet.py")
    pdet = gpd.read_file(pdet_path, layer=cfg["pdet"]["layer"])
    exp = cfg["pdet"]["expected_municipalities"]
    qc.expect("SEL-01", "Municipios PDET de entrada", len(pdet) == exp and pdet.crs.to_epsg() == 4326,
              f"{len(pdet)} (esperados {exp}), EPSG:{pdet.crs.to_epsg()}")
    codes = pdet["mpio_cdpmp"].astype(str).tolist()

    # ---- Microsoft
    idx_path = ba.repo_path(ms["index_file"])
    fetch(ms["index_url"], idx_path, args.refresh)
    index = pd.read_csv(idx_path, dtype=str)
    pais = index[index["Location"] == ms["location"]]
    qc.expect("SEL-02", f"Particiones de Microsoft para {ms['location']}", len(pais) > 0,
              f"{len(pais)} quadkeys de nivel {pais['QuadKey'].str.len().max()} en el índice "
              f"(subido {', '.join(sorted(pais['UploadDate'].unique()))})")
    dup = int(pais["QuadKey"].duplicated().sum())
    qc.expect("SEL-03", "Un archivo por quadkey en el índice", dup == 0, f"{dup} quadkeys repetidos")
    cat_ms = ba.select_microsoft(index, pdet, ms["location"], buffer_deg)
    qc.add("SEL-04", "Quadkeys de Microsoft que tocan PDET", ba.OK,
           f"{len(cat_ms)} de {len(pais)} (~{cat_ms['size_bytes'].sum() / 1e6:,.1f} MB de "
           f"~{pais['Size'].map(ba.parse_size).sum() / 1e6:,.1f} MB del país)")
    ba.check_coverage(cat_ms, codes, qc, "SEL-05", "Microsoft")

    # ---- Google
    tiles_path = ba.repo_path(gg["tiles_file"])
    fetch(gg["tiles_url"], tiles_path, args.refresh)
    tiles = gpd.read_file(tiles_path)
    objects = ba.list_bucket(gg["bucket_api"], gg["prefix"])
    qc.expect("SEL-06", "Objetos del bucket de Google = celdas de tiles.geojson", len(objects) == len(tiles),
              f"{len(objects)} objetos / {len(tiles)} celdas S2", nivel=ba.AVISO)
    cat_gg, missing = ba.select_google(tiles, objects, pdet, gg["prefix"], buffer_deg)
    qc.expect("SEL-07", "Celdas seleccionadas con archivo en el bucket", not missing,
              f"sin archivo: {missing}" if missing else "todas tienen tamaño y MD5 publicados")
    sizes = dict(zip(tiles["tile_id"].astype(str), tiles["size_mb"]))
    diff = [p for p, b in zip(cat_gg["partition_id"], cat_gg["size_bytes"]) if abs(b / 1e6 - sizes[p]) > 0.1]
    qc.expect("SEL-08", "Tamaño en tiles.geojson = tamaño en el bucket", not diff,
              f"distintos: {diff}" if diff else f"{len(cat_gg)} celdas coinciden", nivel=ba.AVISO)
    total_gg = sum(int(o["size"]) for o in objects)
    qc.add("SEL-09", "Celdas S2 de Google que tocan PDET", ba.OK,
           f"{len(cat_gg)} de {len(tiles)} ({cat_gg['size_bytes'].sum() / 1e6:,.1f} MB de {total_gg / 1e9:,.1f} GB)")
    ba.check_coverage(cat_gg, codes, qc, "SEL-10", "Google")

    catalog = pd.concat([cat_ms, cat_gg], ignore_index=True)
    out = ba.repo_path(cfg["selection"]["catalog_csv"])
    out.parent.mkdir(parents=True, exist_ok=True)
    catalog.to_csv(out, index=False, encoding="utf-8")

    o = cfg["output"]
    ba.write_qc(ba.repo_path(o["qc_json"]), ba.repo_path(o["qc_md"]), "seleccion", qc,
                {"buffer_deg": buffer_deg, "catalogo": cfg["selection"]["catalog_csv"],
                 "particiones": catalog.groupby("source").size().to_dict()})
    print(f"\nCatálogo: {out.relative_to(ba.repo_path('.'))} ({len(cat_ms)} Microsoft + {len(cat_gg)} Google)")
    s = qc.summary()
    print(f"Controles: {s[ba.OK]} OK, {s[ba.AVISO]} AVISO, {s[ba.FALLA]} FALLA")
    if qc.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
