#!/usr/bin/env python3
"""Carga las huellas de edificios (salida GeoParquet del ETL) en MongoDB de forma eficiente.

Técnicas de carga masiva:
  * Lectura por row groups (50 000 filas) con buildings_etl.iter_documents: nunca se carga una partición completa.
  * insert_many(ordered=False) en lotes: un documento defectuoso no detiene el lote y el servidor puede paralelizar.
  * Un proceso por partición, cada uno con su propia conexión (4 procesos por defecto, params.yaml).
  * Los índices (2dsphere y compuesto) se crean DESPUÉS de la carga: indexar durante la inserción es mucho más lento.
  * Reanudable: cada partición cargada queda en ingestion_log con el SHA-256 de su archivo de entrada;
    una partición ya cargada se omite y una interrumpida se borra (por source_file) y se vuelve a cargar.
  * Verificación: documentos en la colección = filas escritas por el ETL, en total y por municipio.

Uso:
    python src/02_load_buildings.py --source all --dry-run --limit-partitions 2   # lee sin escribir en MongoDB
    python src/02_load_buildings.py --source all                                 # carga + índices + verificación
    python src/02_load_buildings.py --source google --workers 2 --batch-size 10000
    python src/02_load_buildings.py --benchmark google                           # compara tamaños de lote
    python src/02_load_buildings.py --verify                                     # solo verifica conteos
    python src/02_load_buildings.py --source all --drop                          # empieza de cero
Métricas: docs/rendimiento/load_metrics.json y .md
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import yaml

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))
from buildings_etl import iter_documents  # noqa: E402

SOURCES = ("microsoft", "google")


def load_config():
    cfg = yaml.safe_load((ROOT / "config/params.yaml").read_text(encoding="utf-8")) or {}
    extra = yaml.safe_load((ROOT / "config/buildings_load.yaml").read_text(encoding="utf-8")) or {}
    cfg.update(extra)
    return cfg


def repo_path(p):
    return ROOT / p


def discover(source, cfg):
    """Particiones del ETL con su _SUCCESS.json, las más grandes primero (mejor reparto entre procesos)."""
    base = repo_path(cfg["input"]["processed_dir"]) / source
    parts = []
    for d in sorted(base.glob("*")):
        f = d / "_SUCCESS.json"
        if d.is_dir() and f.exists():
            info = json.loads(f.read_text(encoding="utf-8"))
            parts.append({"dir": str(d), "id": d.name, "info": info})
    parts.sort(key=lambda p: -int(p["info"].get("escritos", 0)))
    return parts


def insert_batches(col, docs, batch_size):
    """insert_many sin orden, en lotes. Devuelve (insertados, fallidos)."""
    from pymongo.errors import BulkWriteError

    ok = bad = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        try:
            ok += len(col.insert_many(batch, ordered=False).inserted_ids)
        except BulkWriteError as e:
            n_err = len(e.details.get("writeErrors", []))
            ok += len(batch) - n_err
            bad += n_err
    return ok, bad


def _db(cfg):
    from pymongo import MongoClient

    client = MongoClient(cfg["mongo"]["uri"])
    return client, client[cfg["mongo"]["database"]]


def load_partition(task):
    """Carga una partición. Idempotente: se omite si ya está 'ok' en ingestion_log con el mismo SHA-256."""
    cfg, source, part, dry_run, batch_size = task
    info = part["info"]
    archivo = info["archivo"]
    t0 = time.time()
    col = log = client = None
    if not dry_run:
        client, db = _db(cfg)
        coll_name = cfg["collections"][source]
        col, log = db[coll_name], db[cfg["collections"]["ingestion_log"]]
        if log.find_one({"dataset": coll_name, "file": archivo, "status": "ok",
                         "checksum": info["sha256_entrada"]}):
            client.close()
            return {"source": source, "partition": part["id"], "skipped": True}
        col.delete_many({"source_file": archivo})        # restos de una corrida interrumpida
        log.delete_many({"dataset": coll_name, "file": archivo})

    read = inserted = failed = 0
    pending = []
    for docs in iter_documents(part["dir"]):
        read += len(docs)
        if dry_run:
            continue
        pending.extend(docs)
        if len(pending) >= batch_size:
            ok, bad = insert_batches(col, pending, batch_size)
            inserted += ok
            failed += bad
            pending.clear()
    if pending and not dry_run:
        ok, bad = insert_batches(col, pending, batch_size)
        inserted += ok
        failed += bad

    secs = time.time() - t0
    expected = int(info.get("escritos", 0))
    res = {"source": source, "partition": part["id"], "file": archivo, "expected": expected, "read": read,
           "inserted": inserted, "failed": failed, "seconds": round(secs, 2),
           "docs_per_s": round(read / secs, 1) if secs else None}
    if not dry_run:
        in_db = col.count_documents({"source_file": archivo})
        status = "ok" if (in_db == expected and failed == 0) else "mismatch"
        res.update({"in_db": in_db, "status": status})
        log.insert_one({"dataset": cfg["collections"][source], "file": archivo, "status": status,
                        "rows_read": int(info.get("leidos", read)), "rows_inserted": inserted,
                        "rows_rejected": failed, "outside_pdet": int(info.get("fuera_pdet", 0)),
                        "checksum": info["sha256_entrada"], "partition": part["id"],
                        "loaded_at": datetime.now(timezone.utc)})
        client.close()
    elif read != expected:
        res["status"] = "mismatch"
    return res


def create_indexes(source, cfg):
    from pymongo import ASCENDING, GEOSPHERE

    client, db = _db(cfg)
    col = db[cfg["collections"][source]]
    specs = [("geometry_2dsphere", [("geometry", GEOSPHERE)]),
             ("municipality_area", [tuple(k) for k in cfg["indexes"]["compound"]]),
             ("source_file_1", [("source_file", ASCENDING)])]
    if source == "google" and cfg["indexes"].get("google_confidence"):
        specs.append(("confidence_1", [("confidence", ASCENDING)]))
    out = {}
    for name, keys in specs:
        t = time.time()
        col.create_index(keys, name=name)
        out[name] = round(time.time() - t, 2)
        print(f"  índice {name}: {out[name]} s")
    client.close()
    return out


def verify(source, cfg):
    """Compara documentos en MongoDB con lo escrito por el ETL: total y por municipio."""
    parts = discover(source, cfg)
    exp_total = sum(int(p["info"].get("escritos", 0)) for p in parts)
    exp_mpio = {}
    for p in parts:
        for code, n in (p["info"].get("por_municipio") or {}).items():
            exp_mpio[code] = exp_mpio.get(code, 0) + int(n)
    client, db = _db(cfg)
    col = db[cfg["collections"][source]]
    total = col.count_documents({})
    got = {r["_id"]: r["n"] for r in col.aggregate([{"$group": {"_id": "$municipality_code", "n": {"$sum": 1}}}],
                                                   allowDiskUse=True)}
    client.close()
    diff = {c: (exp_mpio.get(c, 0), got.get(c, 0)) for c in set(exp_mpio) | set(got)
            if exp_mpio.get(c, 0) != got.get(c, 0)}
    return {"expected_total": exp_total, "in_db_total": total, "municipalities_expected": len(exp_mpio),
            "municipalities_in_db": len(got), "municipalities_with_diff": len(diff),
            "diff_sample": dict(list(diff.items())[:10]), "ok": total == exp_total and not diff}


def benchmark(source, cfg):
    """Compara docs/s para distintos tamaños de lote con una muestra de la partición más pequeña útil."""
    parts = [p for p in discover(source, cfg) if int(p["info"].get("escritos", 0)) > 0]
    if not parts:
        raise SystemExit(f"No hay particiones de {source} en {cfg['input']['processed_dir']}")
    n = cfg["benchmark"]["sample_docs"]
    part = next((p for p in reversed(parts) if int(p["info"]["escritos"]) >= n), parts[0])
    docs = []
    for batch in iter_documents(part["dir"]):
        docs.extend(batch)
        if len(docs) >= n:
            break
    docs = docs[:n]
    print(f"Muestra: {len(docs)} documentos de {source}/{part['id']}")
    client, db = _db(cfg)
    results = []
    for bs in cfg["benchmark"]["batch_sizes"]:
        db.bench_tmp.drop()
        sample = [dict(d) for d in docs]                    # insert_many agrega _id: se copia en cada corrida
        t = time.time()
        ok, _ = insert_batches(db.bench_tmp, sample, bs)
        s = time.time() - t
        results.append({"batch_size": bs, "docs": ok, "seconds": round(s, 2), "docs_per_s": round(ok / s, 1)})
        print(f"  lote {bs:>6}: {ok / s:>10,.0f} docs/s")
    db.bench_tmp.drop()
    client.close()
    return {"source": source, "partition": part["id"], "sample_docs": len(docs), "results": results}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_metrics(metrics, cfg):
    jp = repo_path(cfg["output"]["metrics_json"])
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# Rendimiento de la carga de edificios", "",
             f"Procesos: {metrics.get('workers')} · lote: {metrics.get('batch_size')} · "
             f"{metrics.get('started_at')} → {metrics.get('finished_at')}", "",
             "| Fuente | Particiones | Documentos | Segundos | Docs/s | Índices (s) |", "|---|---:|---:|---:|---:|---|"]
    for s, m in (metrics.get("sources") or {}).items():
        t = m["totals"]
        idx = ", ".join(f"{k}: {v}" for k, v in (m.get("index_seconds") or {}).items())
        lines.append(f"| {s} | {t['partitions']} | {t['inserted']:,} | {t['seconds']} | {t['docs_per_s']:,} | {idx} |")
    for s, v in (metrics.get("verify") or {}).items():
        lines += ["", f"Verificación {s}: esperado {v['expected_total']:,}, en MongoDB {v['in_db_total']:,}, "
                      f"municipios con diferencia {v['municipalities_with_diff']} → {'OK' if v['ok'] else 'FALLA'}"]
    b = metrics.get("benchmark")
    if b:
        lines += ["", f"## Tamaño de lote ({b['source']}/{b['partition']}, {b['sample_docs']:,} documentos)", "",
                  "| Lote | Segundos | Docs/s |", "|---:|---:|---:|"]
        lines += [f"| {r['batch_size']} | {r['seconds']} | {r['docs_per_s']:,} |" for r in b["results"]]
    repo_path(cfg["output"]["metrics_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--batch-size", type=int)
    ap.add_argument("--limit-partitions", type=int)
    ap.add_argument("--dry-run", action="store_true", help="lee las particiones sin escribir en MongoDB")
    ap.add_argument("--drop", action="store_true", help="vacía la colección y su bitácora antes de cargar")
    ap.add_argument("--skip-indexes", action="store_true")
    ap.add_argument("--benchmark", choices=SOURCES, help="compara tamaños de lote con una muestra")
    ap.add_argument("--verify", action="store_true", help="solo compara conteos con lo escrito por el ETL")
    a = ap.parse_args()

    cfg = load_config()
    workers = a.workers or cfg["load"]["workers"]
    batch = a.batch_size or cfg["load"]["batch_size"]
    sources = list(SOURCES) if a.source == "all" else [a.source]
    mpath = repo_path(cfg["output"]["metrics_json"])

    if a.benchmark:
        m = _read_json(mpath)
        m["benchmark"] = benchmark(a.benchmark, cfg)
        write_metrics(m, cfg)
        return 0
    if a.verify:
        m = _read_json(mpath)
        m["verify"] = {s: verify(s, cfg) for s in sources}
        for s, v in m["verify"].items():
            print(f"[{s}] esperado {v['expected_total']:,} · MongoDB {v['in_db_total']:,} · "
                  f"municipios con diferencia {v['municipalities_with_diff']} → {'OK' if v['ok'] else 'FALLA'}")
        write_metrics(m, cfg)
        return 0 if all(v["ok"] for v in m["verify"].values()) else 1

    old = _read_json(mpath) if not a.dry_run else {}
    metrics = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "workers": workers,
               "batch_size": batch, "sources": {}, "verify": old.get("verify", {})}
    if "benchmark" in old:
        metrics["benchmark"] = old["benchmark"]
    for source in sources:
        parts = discover(source, cfg)
        if a.limit_partitions:
            parts = parts[:a.limit_partitions]
        if not parts:
            print(f"[{source}] no hay particiones en {cfg['input']['processed_dir']}/{source}: ejecute src/01b_etl_buildings.py")
            continue
        if a.drop and not a.dry_run:
            client, db = _db(cfg)
            db[cfg["collections"][source]].drop()
            db[cfg["collections"]["ingestion_log"]].delete_many({"dataset": cfg["collections"][source]})
            client.close()
        print(f"[{source}] {len(parts)} particiones, {workers} procesos, lotes de {batch}"
              f"{' (dry-run: no se escribe)' if a.dry_run else ''}")
        t0 = time.time()
        results = []
        with Pool(workers) as pool:
            for r in pool.imap_unordered(load_partition, [(cfg, source, p, a.dry_run, batch) for p in parts]):
                results.append(r)
                print("  ", {k: r[k] for k in r if k in ("partition", "read", "inserted", "seconds", "docs_per_s",
                                                         "skipped", "status")})
        secs = time.time() - t0
        done = [r for r in results if not r.get("skipped")]
        n = sum(r["read"] for r in done) if a.dry_run else sum(r["inserted"] for r in done)
        tot = {"partitions": len(results), "skipped": len(results) - len(done), "inserted": n,
               "failed": sum(r.get("failed", 0) for r in done), "seconds": round(secs, 1),
               "docs_per_s": round(n / secs, 1) if secs else 0}
        bad = [r["partition"] for r in done if r.get("status") == "mismatch"]
        metrics["sources"][source] = {"totals": tot, "partitions": results, "mismatch": bad}
        print(f"[{source}] {tot}" + (f"  ¡PARTICIONES CON DIFERENCIA: {bad}!" if bad else ""))
        if not a.dry_run and not a.skip_indexes:
            print(f"[{source}] creando índices (después de la carga masiva)")
            metrics["sources"][source]["index_seconds"] = create_indexes(source, cfg)
        if not a.dry_run and not a.limit_partitions:
            metrics["verify"][source] = verify(source, cfg)
            v = metrics["verify"][source]
            print(f"[{source}] verificación: esperado {v['expected_total']:,} · MongoDB {v['in_db_total']:,} → "
                  f"{'OK' if v['ok'] else 'FALLA'}")
    metrics["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not a.dry_run:
        write_metrics(metrics, cfg)
        print(f"Métricas en {cfg['output']['metrics_json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
