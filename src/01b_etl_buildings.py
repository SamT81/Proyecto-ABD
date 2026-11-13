#!/usr/bin/env python3
"""ETL de huellas de edificios: de los archivos descargados a GeoParquet limpio por fuente y partición.

Uso:
    python src/01b_etl_buildings.py                        # ambas fuentes, reutiliza particiones ya procesadas
    python src/01b_etl_buildings.py --source google        # solo una fuente
    python src/01b_etl_buildings.py --partition 8e1        # solo una partición (pruebas)
    python src/01b_etl_buildings.py --force                # reprocesa aunque la salida exista

Por cada edificio: repara la geometría (make_valid), la reduce a Polygon, redondea a 6 decimales, orienta los
anillos, calcula el punto representativo y le asigna el municipio PDET que lo contiene. Los edificios fuera de
PDET se descartan. El área se calcula en EPSG:9377 (Microsoft) o se conserva area_in_meters (Google).
Salida: data/processed/buildings/<fuente>/<partición>/part-*.parquet y docs/calidad/etl_buildings_report.{json,md}.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildings_acquisition as ba  # noqa: E402
import buildings_etl as be  # noqa: E402


def load_tasks(cfg, params, args):
    catalog = pd.read_csv(ba.repo_path(cfg["selection"]["catalog_csv"]), dtype={"partition_id": str},
                          keep_default_na=False)
    manifest = json.loads(ba.repo_path(cfg["output"]["manifest"]).read_text(encoding="utf-8"))
    files = {a["archivo"]: a for a in manifest["archivos"]}
    if args.source:
        catalog = catalog[catalog["source"] == args.source]
    if args.partition:
        catalog = catalog[catalog["partition_id"].isin(args.partition)]

    etl = cfg["etl"]
    out_root = ba.repo_path(etl["out_dir"])
    tasks, missing = [], []
    for row in catalog.itertuples():
        raw = ba.repo_path(cfg["sources"][row.source]["raw_dir"]) / row.file_name
        meta = files.get(row.file_name)
        if not raw.exists() or not meta or meta.get("estado") not in ("descargado", "reutilizado"):
            missing.append(f"{row.source}/{row.partition_id}")
            continue
        tasks.append({
            "source": row.source,
            "partition_id": row.partition_id,
            "raw_file": str(raw),
            "sha256": meta["sha256"],
            "municipios": row.municipios.split(";"),
            "out_dir": str(out_root / row.source / row.partition_id),
            "pdet_gpkg": str(ba.repo_path(cfg["pdet"]["gpkg"])),
            "pdet_layer": cfg["pdet"]["layer"],
            "area_crs": params["crs"]["area"],
            "chunk_rows": etl["chunk_rows"],
            "row_group_size": etl["row_group_size"],
            "precision": etl["coord_precision"],
            "prefilter_deg": etl["prefilter_deg"],
        })
    return tasks, missing


def previous_summary(task):
    """Resumen de una corrida anterior si la salida existe y viene del mismo archivo de entrada."""
    ok = Path(task["out_dir"]) / "_SUCCESS.json"
    if not ok.exists():
        return None
    s = json.loads(ok.read_text(encoding="utf-8"))
    return s if s.get("sha256_entrada") == task["sha256"] else None


def read_hashes(out_dir):
    """Hash de la geometría de cada edificio escrito (para detectar duplicados entre particiones)."""
    import pyarrow.parquet as pq
    import shapely

    hs = []
    for f in sorted(Path(out_dir).glob("part-*.parquet")):
        wkb = pq.read_table(f, columns=["geometry"]).column("geometry").to_numpy(zero_copy_only=False)
        wkb = shapely.to_wkb(shapely.from_wkb(wkb))   # misma serialización que en el ETL
        hs.append(pd.util.hash_array(wkb.astype(object)).astype(np.uint64))
    return np.concatenate(hs) if hs else np.array([], dtype=np.uint64)


def verify_output(out_dir, source, codes):
    """Relee la salida de una partición y comprueba esquema, tipos, CRS y códigos."""
    import geopandas as gpd

    n, problems = 0, []
    for f in sorted(Path(out_dir).glob("part-*.parquet")):
        gdf = gpd.read_parquet(f)
        n += len(gdf)
        if list(gdf.columns) != be.OUTPUT_COLUMNS[source]:
            problems.append(f"{f.name}: columnas {list(gdf.columns)}")
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            problems.append(f"{f.name}: CRS {gdf.crs}")
        if not (gdf.geom_type == "Polygon").all():
            problems.append(f"{f.name}: tipos {gdf.geom_type.value_counts().to_dict()}")
        if not gdf.is_valid.all():
            problems.append(f"{f.name}: {int((~gdf.is_valid).sum())} inválidas")
        bad = set(gdf["municipality_code"]) - codes
        if bad:
            problems.append(f"{f.name}: códigos fuera de PDET {sorted(bad)[:5]}")
        if gdf[["area_m2", "municipality_code"]].isna().any().any():
            problems.append(f"{f.name}: nulos en area_m2 o municipality_code")
    return n, problems


def render_md(report):
    lines = ["# Reporte del ETL de huellas de edificios", "",
             f"Generado por `src/01b_etl_buildings.py` el {report['generado_utc']} "
             f"({report['segundos']} s). Detalle por partición en `etl_buildings_report.json`.", ""]
    lines += ["## Resumen por fuente", "",
              "| Fuente | Particiones | Leídos | Fuera de PDET | Reparados | Multiparte reducidos | Rechazados | "
              "Escritos | Municipios con edificios | Duplicados exactos |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s, r in report["fuentes"].items():
        lines.append(f"| {s} | {r['particiones']} | {r['leidos']:,} | {r['fuera_pdet']:,} | {r['reparados']:,} | "
                     f"{r['multiparte_reducidos']:,} | {r['rechazados']:,} | {r['escritos']:,} | "
                     f"{r['municipios_con_edificios']}/170 | {r['duplicados_exactos']:,} |")
    lines += ["", "Rechazados por motivo:", ""]
    for s, r in report["fuentes"].items():
        motivos = ", ".join(f"{k}: {v:,}" for k, v in r["rechazados_por_motivo"].items()) or "ninguno"
        lines.append(f"* {s}: {motivos}")
    g = report["fuentes"].get("google", {}).get("area_google_vs_9377")
    if g:
        lines += ["", "## Área de Google frente a EPSG:9377", "",
                  f"Sobre {g['n']:,} edificios de Google dentro de PDET, la diferencia relativa entre `area_in_meters` "
                  f"y el área recalculada en EPSG:9377 tiene mediana absoluta de {g['mediana_abs_rel'] * 100:.3f} %, "
                  f"p95 de {g['p95_abs_rel'] * 100:.3f} % y p99 de {g['p99_abs_rel'] * 100:.3f} % "
                  f"(media con signo {g['media_rel'] * 100:+.3f} %)."]
    lines += ["", "## Controles", "", "| Id | Control | Resultado | Detalle |", "|---|---|---|---|"]
    for c in report["controles"]:
        lines.append(f"| {c['id']} | {c['control']} | {c['resultado']} | {str(c['detalle']).replace('|', '/')} |")
    lines += ["", "## Edificios por municipio (10 con más edificios)", ""]
    for s, r in report["fuentes"].items():
        top = sorted(r["por_municipio"].items(), key=lambda kv: -kv[1])[:10]
        lines.append(f"* {s}: " + ", ".join(f"{k} ({v:,})" for k, v in top))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--source", choices=["microsoft", "google"])
    ap.add_argument("--partition", nargs="+")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int)
    args = ap.parse_args()

    cfg = ba.load_buildings_config(args.config)
    params = ba.load_config(ba.repo_path("config/params.yaml"))
    tasks, missing = load_tasks(cfg, params, args)
    if missing:
        print(f"[AVISO] {len(missing)} particiones sin descargar (ejecute 00e): {missing[:10]}")
    workers = args.workers or params["load"]["workers"]

    import geopandas as gpd
    codes = set(gpd.read_file(ba.repo_path(cfg["pdet"]["gpkg"]), layer=cfg["pdet"]["layer"])["mpio_cdpmp"])

    t0 = time.time()
    summaries, todo = [], []
    for t in tasks:
        prev = None if args.force else previous_summary(t)
        if prev:
            prev["hashes"] = read_hashes(t["out_dir"])
            prev["reutilizado"] = True
            summaries.append(prev)
        else:
            todo.append(t)
    print(f"{len(tasks)} particiones: {len(summaries)} ya procesadas, {len(todo)} por procesar con {workers} procesos")

    # Las particiones grandes primero para repartir mejor el trabajo entre procesos.
    todo.sort(key=lambda t: -Path(t["raw_file"]).stat().st_size)
    errors = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(be.process_partition, t): t for t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                s = fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{t['source']}/{t['partition_id']}: {str(exc)[:200]}")
                print(f"[{i:3}/{len(todo)}] [FALLA] {t['source']} {t['partition_id']}: {exc}")
                continue
            summaries.append(s)
            print(f"[{i:3}/{len(todo)}] {s['source']:9} {s['partition_id']:10} leídos {s['leidos']:>10,} "
                  f"escritos {s.get('escritos', 0):>9,} ({s['segundos']} s)")

    # ---------------------------------------------------------------- consolidación y controles
    qc = ba.QCReport()
    report = {"generado_utc": ba.now_iso(), "segundos": round(time.time() - t0, 1),
              "parametros": {k: cfg["etl"][k] for k in cfg["etl"]} | {"area_crs": params["crs"]["area"]},
              "fuentes": {}, "particiones": []}
    for source in ("microsoft", "google"):
        ss = [s for s in summaries if s["source"] == source]
        if not ss:
            continue
        expected = sum(1 for t in tasks if t["source"] == source)
        motivos = {}
        for s in ss:
            for k, v in s.items():
                if k.startswith("rechazados:") and v:
                    motivos[k.split(":", 1)[1]] = motivos.get(k.split(":", 1)[1], 0) + v
        per_mpio = {}
        for s in ss:
            for k, v in s["por_municipio"].items():
                per_mpio[k] = per_mpio.get(k, 0) + v
        hashes = np.concatenate([s["hashes"] for s in ss]) if ss else np.array([])
        dups = int(len(hashes) - len(np.unique(hashes)))
        tot = {k: sum(s.get(k, 0) for s in ss) for k in ("leidos", "fuera_pdet", "reparados",
                                                          "multiparte_reducidos", "escritos")}
        r = {"particiones": len(ss), **tot, "rechazados": sum(motivos.values()),
             "rechazados_por_motivo": motivos, "duplicados_exactos": dups,
             "municipios_con_edificios": len(per_mpio), "por_municipio": dict(sorted(per_mpio.items()))}
        if source == "google":
            ws = [(s["area_google_vs_9377"], s["escritos"]) for s in ss if s.get("area_google_vs_9377")]
            if ws:
                n = sum(w["n"] for w, _ in ws)
                # Agregado ponderado por número de edificios de cada partición (aproximación de los percentiles).
                r["area_google_vs_9377"] = {
                    "n": n, **{k: float(sum(w[k] * w["n"] for w, _ in ws) / n)
                               for k in ("media_rel", "mediana_abs_rel", "p95_abs_rel", "p99_abs_rel")}}
        report["fuentes"][source] = r

        tag = f"ETL-{source[0].upper()}"
        qc.expect(f"{tag}1", f"Particiones procesadas ({source})", len(ss) == expected,
                  f"{len(ss)}/{expected}" + (f"; con error: {[e for e in errors if e.startswith(source)]}"
                                             if len(ss) < expected else ""))
        written, problems = 0, []
        out_root = ba.repo_path(cfg["etl"]["out_dir"]) / source
        for s in ss:
            n, p = verify_output(out_root / s["partition_id"], source, codes)
            written += n
            problems += p
        qc.expect(f"{tag}2", f"Salida releída: esquema, EPSG:4326, Polygon válidos y códigos PDET ({source})",
                  not problems, "; ".join(problems[:5]) if problems else f"{written:,} registros")
        qc.expect(f"{tag}3", f"Registros releídos = registros escritos ({source})", written == r["escritos"],
                  f"{written:,} / {r['escritos']:,}")
        qc.expect(f"{tag}4", f"Municipios PDET con al menos un edificio ({source})", len(per_mpio) == len(codes),
                  f"{len(per_mpio)}/{len(codes)}" + (f"; sin edificios: {sorted(codes - set(per_mpio))}"
                                                     if len(per_mpio) < len(codes) else ""), nivel=ba.AVISO)
        dentro = r["escritos"] + r["rechazados"]
        tasa = r["rechazados"] / dentro * 100 if dentro else 0
        qc.expect(f"{tag}5", f"Geometrías rechazadas ({source})", tasa < 0.1,
                  f"{r['rechazados']:,} ({tasa:.4f} %); reparadas {r['reparados']:,}, multiparte reducidas "
                  f"{r['multiparte_reducidos']:,}", nivel=ba.AVISO)
        qc.expect(f"{tag}6", f"Sin geometrías duplicadas exactas ({source})", dups == 0,
                  f"{dups:,} duplicadas de {len(hashes):,}", nivel=ba.AVISO)
        if source == "google" and r.get("area_google_vs_9377"):
            g = r["area_google_vs_9377"]
            qc.expect(f"{tag}7", "area_in_meters de Google coherente con el área en EPSG:9377",
                      g["mediana_abs_rel"] < 0.02, f"mediana {g['mediana_abs_rel'] * 100:.3f} %, "
                      f"p95 {g['p95_abs_rel'] * 100:.3f} %", nivel=ba.AVISO)

    for s in sorted(summaries, key=lambda s: (s["source"], s["partition_id"])):
        report["particiones"].append({k: v for k, v in s.items() if k not in ("hashes", "por_municipio")})
    report["controles"] = qc.checks
    report["resumen_controles"] = qc.summary()
    ba.write_json(ba.repo_path(cfg["etl"]["report_json"]), report)
    ba.repo_path(cfg["etl"]["report_md"]).write_text(render_md(report), encoding="utf-8")

    for source, r in report["fuentes"].items():
        print(f"{source}: {r['escritos']:,} edificios en {r['municipios_con_edificios']} municipios "
              f"(leídos {r['leidos']:,}, fuera de PDET {r['fuera_pdet']:,}, rechazados {r['rechazados']:,})")
    s = qc.summary()
    print(f"Controles: {s[ba.OK]} OK, {s[ba.AVISO]} AVISO, {s[ba.FALLA]} FALLA. "
          f"Reporte: {cfg['etl']['report_md']}")
    if qc.failed or errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
