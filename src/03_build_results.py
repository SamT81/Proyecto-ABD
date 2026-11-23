#!/usr/bin/env python3
"""Entrega 4: construye la colección `results` (métricas por municipio y fuente) y el análisis de sensibilidad.

Para cada fuente, una agregación de MongoDB agrupa por municipality_code (sin join espacial: el municipio se asignó en
el ETL) y escribe el resultado con $merge en `results`, junto con los parámetros del criterio de techo apto y la fecha
de cálculo. Es repetible: volver a ejecutarlo reemplaza los documentos de (municipio, fuente) en vez de duplicarlos.

Criterio de techo apto (config/params.yaml):  area_m2 >= min_area_m2  y, solo en Google, confidence >= min_confidence.

Uso:
    python src/03_build_results.py                  # results + CSV + sensibilidad + verificación
    python src/03_build_results.py --skip-sensitivity
    python src/03_build_results.py --export-only    # solo reescribe los CSV desde results
    python src/03_build_results.py --dry-run        # corre las agregaciones sin escribir en results
Salida: docs/resultados/results.csv, sensibilidad.csv y resumen_resultados.md
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("microsoft", "google")


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_config():
    cfg = {}
    for f in ("params.yaml", "spatial.yaml", "buildings_load.yaml", "results.yaml"):
        _merge(cfg, yaml.safe_load((ROOT / "config" / f).read_text(encoding="utf-8")) or {})
    return cfg


def suitable_cond(source, min_area, min_conf):
    """Expresión de agregación: 1 si el edificio es un techo apto."""
    conds = [{"$gte": ["$area_m2", min_area]}]
    if source == "google":
        conds.append({"$gte": ["$confidence", min_conf]})
    return {"$and": conds}


def build_pipeline(source, min_area, min_conf, crs_area, computed_at, merge_into=None):
    cond = suitable_cond(source, min_area, min_conf)
    pipe = [
        {"$group": {"_id": "$municipality_code",
                    "building_count": {"$sum": 1},
                    "total_roof_area_m2": {"$sum": "$area_m2"},
                    "suitable_count": {"$sum": {"$cond": [cond, 1, 0]}},
                    "suitable_area_m2": {"$sum": {"$cond": [cond, "$area_m2", 0]}}}},
        {"$project": {"_id": 0, "municipality_code": "$_id", "source": {"$literal": source},
                      "building_count": 1, "total_roof_area_m2": 1, "suitable_count": 1, "suitable_area_m2": 1,
                      "params": {"$literal": {"min_area_m2": min_area,
                                              "min_confidence": min_conf if source == "google" else None,
                                              "crs_area": crs_area}},
                      "computed_at": {"$literal": computed_at}}},
    ]
    if merge_into:
        pipe.append({"$merge": {"into": merge_into, "on": ["municipality_code", "source"],
                                "whenMatched": "replace", "whenNotMatched": "insert"}})
    return pipe


def build_sensitivity_pipeline(source, grid):
    """Una sola pasada por la colección: un $sum por cada combinación de umbrales."""
    group = {"_id": None, "n": {"$sum": 1}, "area_total": {"$sum": "$area_m2"}}
    combos = []
    for i, (a, c) in enumerate(grid):
        cond = suitable_cond(source, a, c)
        group[f"n_{i}"] = {"$sum": {"$cond": [cond, 1, 0]}}
        group[f"a_{i}"] = {"$sum": {"$cond": [cond, "$area_m2", 0]}}
        combos.append((i, a, c))
    return [{"$group": group}], combos


def sensitivity(col, source, cfg):
    areas = cfg["sensitivity"]["min_area_m2"]
    confs = cfg["sensitivity"]["min_confidence"] if source == "google" else [None]
    grid = [(a, c) for a in areas for c in confs]
    pipe, combos = build_sensitivity_pipeline(source, grid)
    r = list(col.aggregate(pipe, allowDiskUse=True))
    r = r[0] if r else {"n": 0, "area_total": 0}
    rows = []
    for i, a, c in combos:
        rows.append({"source": source, "min_area_m2": a, "min_confidence": c if c is not None else "",
                     "suitable_count": r.get(f"n_{i}", 0), "suitable_area_km2": round(r.get(f"a_{i}", 0) / 1e6, 3),
                     "pct_of_buildings": round(100 * r.get(f"n_{i}", 0) / r["n"], 2) if r["n"] else 0,
                     "pct_of_area": round(100 * r.get(f"a_{i}", 0) / r["area_total"], 2) if r["area_total"] else 0})
    return rows


RESULT_COLS = ["municipality_code", "name", "department_name", "pdet_subregion", "source", "building_count",
               "total_roof_area_m2", "suitable_count", "suitable_area_m2", "min_area_m2", "min_confidence",
               "sin_datos", "computed_at"]


def export_rows(results_docs, municipalities):
    """Une results con los nombres de los municipios y completa con ceros los (municipio, fuente) sin edificios."""
    by_key = {(d["municipality_code"], d["source"]): d for d in results_docs}
    rows = []
    for code, m in sorted(municipalities.items()):
        for s in SOURCES:
            d = by_key.get((code, s))
            p = (d or {}).get("params") or {}
            rows.append({
                "municipality_code": code, "name": m.get("name", ""), "department_name": m.get("department_name", ""),
                "pdet_subregion": m.get("pdet_subregion", ""), "source": s,
                "building_count": d["building_count"] if d else 0,
                "total_roof_area_m2": round(d["total_roof_area_m2"], 3) if d else 0.0,
                "suitable_count": d["suitable_count"] if d else 0,
                "suitable_area_m2": round(d["suitable_area_m2"], 3) if d else 0.0,
                "min_area_m2": p.get("min_area_m2", ""), "min_confidence": p.get("min_confidence") or "",
                "sin_datos": d is None,
                "computed_at": d["computed_at"].isoformat() if d and hasattr(d["computed_at"], "isoformat") else ""})
    return rows


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def verify(db, cfg, municipalities):
    """Los totales de results deben coincidir con las colecciones de edificios."""
    out = {}
    res = db[cfg["results"]["collection"]]
    for s in SOURCES:
        n_src = db[cfg["collections"][s]].estimated_document_count()
        agg = list(res.aggregate([{"$match": {"source": s}}, {"$group": {"_id": None, "n": {"$sum": "$building_count"},
                                                                          "m": {"$sum": 1}}}]))
        n_res, n_mun = (agg[0]["n"], agg[0]["m"]) if agg else (0, 0)
        unknown = res.count_documents({"source": s, "municipality_code": {"$nin": list(municipalities)}})
        out[s] = {"buildings_in_collection": n_src, "buildings_in_results": n_res, "municipalities": n_mun,
                  "unknown_codes": unknown, "ok": n_src == n_res and unknown == 0}
    return out


def summary_md(rows, sens, ver, cfg):
    p = cfg["roof_suitability"]
    L = ["# Resultados de la Entrega 4", "",
         f"Criterio de techo apto: área ≥ {p['min_area_m2']} m² y, en Google, confianza ≥ {p['min_confidence']}.", "",
         "| Fuente | Municipios con edificios | Edificios | Área total (km²) | Techos aptos | Área apta (km²) |",
         "|---|---:|---:|---:|---:|---:|"]
    for s in SOURCES:
        r = [x for x in rows if x["source"] == s]
        L.append(f"| {s} | {sum(1 for x in r if not x['sin_datos'])} | {sum(x['building_count'] for x in r):,} | "
                 f"{sum(x['total_roof_area_m2'] for x in r) / 1e6:,.2f} | {sum(x['suitable_count'] for x in r):,} | "
                 f"{sum(x['suitable_area_m2'] for x in r) / 1e6:,.2f} |")
    L += ["", "Verificación frente a las colecciones de edificios: " +
          "; ".join(f"{s} {'OK' if v['ok'] else 'FALLA'} ({v['buildings_in_results']:,} de {v['buildings_in_collection']:,})"
                    for s, v in ver.items()), ""]
    if sens:
        L += ["## Sensibilidad del área apta", "",
              "| Fuente | Área mín. (m²) | Confianza mín. | Techos aptos | Área apta (km²) | % del área |",
              "|---|---:|---:|---:|---:|---:|"]
        L += [f"| {x['source']} | {x['min_area_m2']} | {x['min_confidence']} | {x['suitable_count']:,} | "
              f"{x['suitable_area_km2']:,} | {x['pct_of_area']} |" for x in sens]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-sensitivity", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    from pymongo import MongoClient

    client = MongoClient(cfg["mongo"]["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit("No se pudo conectar a MongoDB (¿docker compose up -d?): " + str(e)[:120])
    db = client[cfg["mongo"]["database"]]
    rcfg, p = cfg["results"], cfg["roof_suitability"]
    municipalities = {m["_id"]: m for m in db[cfg["collections"]["municipalities"]].find(
        {}, {"name": 1, "department_name": 1, "pdet_subregion": 1})}
    if not municipalities:
        raise SystemExit("La colección municipalities está vacía: ejecute src/01_load_municipalities.py")
    res = db[rcfg["collection"]]

    if not a.export_only:
        res.create_index([("municipality_code", 1), ("source", 1)], unique=True, name="municipality_source")
        computed_at = datetime.now(timezone.utc)
        for s in SOURCES:
            col = db[cfg["collections"][s]]
            if col.estimated_document_count() == 0:
                raise SystemExit(f"{cfg['collections'][s]} está vacía: ejecute src/02_load_buildings.py")
            t = time.time()
            pipe = build_pipeline(s, p["min_area_m2"], p["min_confidence"], cfg["crs"]["area"], computed_at,
                                  None if a.dry_run else rcfg["collection"])
            out = list(col.aggregate(pipe, allowDiskUse=True))
            n = len(out) if a.dry_run else res.count_documents({"source": s})
            print(f"[{s}] {n} municipios en {time.time() - t:.1f} s{' (dry-run: no se escribió)' if a.dry_run else ''}")
    if a.dry_run:
        return 0

    sens = []
    if not a.skip_sensitivity and not a.export_only:
        for s in SOURCES:
            t = time.time()
            sens += sensitivity(db[cfg["collections"][s]], s, cfg)
            print(f"[{s}] sensibilidad: {time.time() - t:.1f} s")
        write_csv(ROOT / rcfg["sensitivity_csv"], sens, list(sens[0]))
    elif (ROOT / rcfg["sensitivity_csv"]).exists():
        sens = list(csv.DictReader(open(ROOT / rcfg["sensitivity_csv"], encoding="utf-8")))
        for x in sens:
            x["suitable_count"] = int(x["suitable_count"])
            x["suitable_area_km2"] = float(x["suitable_area_km2"])

    rows = export_rows(list(res.find({}, {"_id": 0})), municipalities)
    write_csv(ROOT / rcfg["csv"], rows, RESULT_COLS)
    ver = verify(db, cfg, municipalities)
    for s, v in ver.items():
        print(f"[{s}] verificación: {v['buildings_in_results']:,} de {v['buildings_in_collection']:,} edificios, "
              f"{v['municipalities']} municipios → {'OK' if v['ok'] else 'FALLA'}")
    (ROOT / rcfg["summary_md"]).write_text(summary_md(rows, sens, ver, cfg), encoding="utf-8")
    print(f"Escrito {rcfg['csv']} ({len(rows)} filas) y {rcfg['summary_md']}")
    return 0 if all(v["ok"] for v in ver.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
