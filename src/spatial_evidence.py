#!/usr/bin/env python3
"""Genera la evidencia de integración espacial NoSQL: índices, controles y consultas con explain().

Uso:  python src/spatial_evidence.py
Salida (carpeta evidence.out_dir de config/spatial.yaml):
    spatial_evidence.json   resultados completos
    spatial_evidence.md     informe legible (para capturas y README)
    spatial_evidence_table.tex   tabla lista para \\input en LaTeX
Termina con código 1 si algún control falla.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from shapely.geometry import box, mapping, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdet_mongo import REPO_ROOT, load_params, summarize_explain  # noqa: E402


def explain(db, coll, flt, hint=None, limit=None):
    cmd = {"find": coll, "filter": flt}
    if hint:
        cmd["hint"] = hint
    if limit:
        cmd["limit"] = limit
    res = db.command({"explain": cmd, "verbosity": "executionStats"})
    return summarize_explain(res)


def point(geom):
    p = shape(geom).representative_point()
    return {"type": "Point", "coordinates": [p.x, p.y]}


def main():
    cfg = load_params()
    coll = cfg["collections"]["municipalities"]
    out = REPO_ROOT / cfg["evidence"]["out_dir"]
    out.mkdir(parents=True, exist_ok=True)

    client = MongoClient(cfg["mongo"]["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit("No se pudo conectar a MongoDB (¿docker compose up -d?): " + str(e)[:120])
    db = client[cfg["mongo"]["database"]]
    col = db[coll]
    checks, queries = [], []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("OK   " if ok else "FALLA"), name, "-", detail)

    # ---- 1. Índices
    indexes = list(col.list_indexes())
    geo = [ix for ix in indexes if "2dsphere" in ix["key"].values()]
    check("índice 2dsphere en geometry", any(ix["key"].get("geometry") == "2dsphere" for ix in geo),
          json.dumps([{ix["name"]: dict(ix["key"])} for ix in indexes]))

    # ---- 2. Controles de integridad sobre lo cargado
    n = col.count_documents({})
    exp = cfg["validation"]["expected_municipalities"]
    check("número de municipios", n == exp, f"{n} cargados, {exp} esperados")
    subs = col.distinct("pdet_subregion")
    expsub = cfg["validation"]["expected_subregions"]
    check("número de subregiones PDET", len(subs) == expsub, f"{len(subs)} encontradas, {expsub} esperadas")
    bad_code = col.count_documents({"_id": {"$not": {"$regex": r"^\d{5}$"}}})
    check("códigos DIVIPOLA de 5 dígitos", bad_code == 0, f"{bad_code} inválidos")
    bad_type = col.count_documents({"geometry.type": {"$ne": "MultiPolygon"}})
    check("geometrías MultiPolygon", bad_type == 0, f"{bad_type} con otro tipo")
    per_sub = {d["_id"]: d["n"] for d in col.aggregate(
        [{"$group": {"_id": "$pdet_subregion", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}])}

    docs = list(col.find({}, {"name": 1, "geometry": 1}).sort("_id", 1))
    if not docs:
        print("La colección está vacía: ejecute primero src/load_to_mongo.py")
        return 1
    k = min(cfg["evidence"]["sample_size"], len(docs))
    step = max(len(docs) // k, 1)
    sample = docs[::step][:k]

    # ---- 3. Consultas espaciales con explain (índice vs. recorrido completo)
    def run(name, desc, flt, expect=None, compare=True):
        with_idx = explain(db, coll, flt)
        row = {"query": name, "description": desc, "plan_index": with_idx}
        if compare:
            row["plan_collscan"] = explain(db, coll, flt, hint={"$natural": 1})
        ids = [d["_id"] for d in col.find(flt, {"_id": 1})]
        row["returned_ids"] = ids[:20]
        row["n_returned"] = len(ids)
        if expect is not None:
            row["expected_ok"] = expect(ids)
        queries.append(row)
        ok = with_idx["uses_index"] and not with_idx["collscan"] and row.get("expected_ok", True)
        check(f"{name}: usa índice 2dsphere", ok,
              f"etapas={with_idx['stages']} índice={with_idx['index_used']} "
              f"claves={with_idx['keys_examined']} docs={with_idx['docs_examined']} "
              f"devueltos={with_idx['n_returned']}")

    for d in sample:
        pt = point(d["geometry"])
        run(f"punto_en_poligono[{d['_id']}]",
            f"$geoIntersects con un punto interior de {d['name']} debe devolver ese municipio",
            {"geometry": {"$geoIntersects": {"$geometry": pt}}},
            expect=lambda ids, i=d["_id"]: i in ids)

    run("punto_en_el_oceano", "punto en el Atlántico (lon -30, lat 0): no debe caer en ningún municipio",
        {"geometry": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [-30.0, 0.0]}}}},
        expect=lambda ids: len(ids) == 0)

    first = sample[0]
    minx, miny, maxx, maxy = shape(first["geometry"]).bounds
    window = mapping(box(minx - 1, miny - 1, maxx + 1, maxy + 1))
    run("ventana_geoWithin", f"$geoWithin con una ventana de 1° alrededor de {first['name']}",
        {"geometry": {"$geoWithin": {"$geometry": window}}},
        expect=lambda ids: first["_id"] in ids)

    run("vecinos_geoIntersects", f"municipios que tocan o se solapan con {first['name']} (incluye el propio)",
        {"geometry": {"$geoIntersects": {"$geometry": first["geometry"]}}},
        expect=lambda ids: first["_id"] in ids)

    run("cercanos_near", f"municipios a menos de {cfg['evidence']['near_max_distance_m']} m de {first['name']}",
        {"geometry": {"$near": {"$geometry": point(first["geometry"]),
                                "$maxDistance": cfg["evidence"]["near_max_distance_m"]}}},
        expect=lambda ids: len(ids) >= 1 and ids[0] == first["_id"], compare=False)

    # ---- 4. Salidas
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mongo_version": client.server_info().get("version"),
        "database": cfg["mongo"]["database"], "collection": coll,
        "documents": n, "indexes": [{"name": ix["name"], "key": dict(ix["key"])} for ix in indexes],
        "municipalities_per_subregion": per_sub, "checks": checks, "queries": queries,
    }
    (out / "spatial_evidence.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                                               encoding="utf-8")
    md = [f"# Evidencia de integración espacial\n",
          f"MongoDB {result['mongo_version']} · base `{result['database']}` · colección `{coll}` · "
          f"{n} documentos · {result['generated_at']}\n",
          "## Índices\n"] + [f"- `{i['name']}`: `{i['key']}`" for i in result["indexes"]]
    md += ["\n## Controles\n", "| Control | Resultado | Detalle |", "|---|---|---|"]
    md += [f"| {c['check']} | {'OK' if c['ok'] else 'FALLA'} | {c['detail']} |" for c in checks]
    md += ["\n## Municipios por subregión\n", "| Subregión | Municipios |", "|---|---|"]
    md += [f"| {s} | {v} |" for s, v in per_sub.items()]
    md += ["\n## Consultas: con índice vs. recorrido completo\n",
           "| Consulta | Plan | Claves | Docs examinados | Devueltos | ms |", "|---|---|---|---|---|---|"]
    for q in queries:
        p = q["plan_index"]
        md.append(f"| {q['query']} | {'/'.join(p['stages'])} | {p['keys_examined']} | "
                  f"{p['docs_examined']} | {p['n_returned']} | {p['millis']} |")
        if "plan_collscan" in q:
            c = q["plan_collscan"]
            md.append(f"| {q['query']} (sin índice) | {'/'.join(c['stages'])} | {c['keys_examined']} | "
                      f"{c['docs_examined']} | {c['n_returned']} | {c['millis']} |")
    (out / "spatial_evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    def tex(s):
        return s.replace("_", r"\_").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")
    rows = []
    for q in queries:
        p = q["plan_index"]
        c = q.get("plan_collscan")
        rows.append(f"\\texttt{{{tex(q['query'])}}} & {tex('/'.join(p['stages']))} & {p['docs_examined']} & "
                    f"{c['docs_examined'] if c else '--'} & {p['n_returned']} \\\\")
    (out / "spatial_evidence_table.tex").write_text(
        "\\begin{tabular}{p{0.34\\linewidth}p{0.28\\linewidth}rrr}\n\\toprule\n"
        "Consulta & Plan ganador & Docs (índice) & Docs (sin índice) & Devueltos \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")
    print(f"\nEvidencia escrita en {out}/")
    return 0 if all(c["ok"] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
