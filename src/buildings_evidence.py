#!/usr/bin/env python3
"""Evidencia de índices espaciales y de integridad de las colecciones de edificios.

Para buildings_microsoft y buildings_google: índices presentes, conteos, consultas con explain("executionStats")
(con índice y, opcionalmente, con recorrido completo), y validación cruzada entre la asignación previa de municipio
(municipality_code) y la consulta espacial $geoWithin sobre el polígono municipal.

Uso:
    python src/buildings_evidence.py                  # ambas colecciones
    python src/buildings_evidence.py --no-collscan    # omite el recorrido completo (lento con millones de docs)
Salida: docs/evidencia_edificios/{evidence.json, evidence.md, evidence_table.tex}
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from buildings_cfg import load_config, repo_path, write_json  # noqa: E402
from pdet_mongo import summarize_explain  # noqa: E402


def explain(db, coll, flt, hint=None, max_ms=None):
    cmd = {"find": coll, "filter": flt}
    if hint:
        cmd["hint"] = hint
    if max_ms:
        cmd["maxTimeMS"] = max_ms
    try:
        return summarize_explain(db.command({"explain": cmd, "verbosity": "executionStats"}))
    except Exception as e:  # noqa: BLE001  (por ejemplo, se superó maxTimeMS)
        return {"error": str(e)[:200], "stages": [], "uses_index": False, "collscan": True,
                "keys_examined": None, "docs_examined": None, "n_returned": None, "millis": None}


def evidence_for(db, coll, cfg, collscan):
    col = db[coll]
    out = {"collection": coll, "checks": [], "queries": []}

    def check(name, ok, detail):
        out["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        print(("OK   " if ok else "FALLA"), f"[{coll}]", name, "-", detail)

    n = col.estimated_document_count()
    out["documents"] = n
    check("colección con documentos", n > 0, f"{n:,} documentos")
    if n == 0:
        return out
    idx = {ix["name"]: dict(ix["key"]) for ix in col.list_indexes()}
    out["indexes"] = idx
    check("índice 2dsphere en geometry", any(v.get("geometry") == "2dsphere" for v in idx.values()), json.dumps(idx))
    check("índice compuesto municipality_code+area_m2",
          any(list(v) == ["municipality_code", "area_m2"] for v in idx.values()), "")
    bad = col.count_documents({"geometry.type": {"$ne": "Polygon"}})
    check("todas las geometrías son Polygon", bad == 0, f"{bad} con otro tipo")
    nocode = col.count_documents({"municipality_code": {"$exists": False}})
    check("todos los edificios tienen municipality_code", nocode == 0, f"{nocode} sin código")
    munis = db[cfg["collections"]["municipalities"]]
    known = set(munis.distinct("_id"))
    codes = set(col.distinct("municipality_code"))
    check("códigos de municipio válidos (subconjunto de los 170 PDET)", codes <= known and len(codes) > 0,
          f"{len(codes)} municipios con edificios; {len(codes - known)} códigos desconocidos")

    # muestra: el edificio más grande de un municipio pequeño, para consultas rápidas
    sample = col.find_one({}, {"geometry": 1, "municipality_code": 1}, sort=[("area_m2", -1)])
    x, y = sample["geometry"]["coordinates"][0][0]            # un vértice del edificio: lo intersecta seguro

    def run(name, desc, flt, compare=True, expect_id=None):
        row = {"query": name, "description": desc, "plan_index": explain(db, coll, flt)}
        if expect_id is not None:
            ids = [d["_id"] for d in col.find(flt, {"_id": 1}).limit(1000)]
            row["expected_ok"] = expect_id in ids
        if compare and collscan:
            row["plan_collscan"] = explain(db, coll, flt, {"$natural": 1}, cfg["evidence"]["collscan_max_ms"])
        out["queries"].append(row)
        p = row["plan_index"]
        check(f"{name}: usa índice espacial", p["uses_index"] and not p["collscan"] and row.get("expected_ok", True),
              f"etapas={p['stages']} claves={p['keys_examined']} docs={p['docs_examined']} devueltos={p['n_returned']}")

    run("punto_en_edificio", "$geoIntersects con un vértice del edificio de muestra: debe devolverlo",
        {"geometry": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [x, y]}}}},
        expect_id=sample["_id"])
    run("cercanos_near", "$near: edificios a menos de 500 m de un punto",
        {"geometry": {"$near": {"$geometry": {"type": "Point", "coordinates": [x, y]}, "$maxDistance": 500}}},
        compare=False)

    # validación cruzada en el municipio con menos edificios (más rápido de consultar)
    top = list(col.aggregate([{"$group": {"_id": "$municipality_code", "n": {"$sum": 1}}}, {"$sort": {"n": 1}}, {"$limit": 1}]))[0]
    muni = munis.find_one({"_id": top["_id"]})
    by_code = top["n"]
    by_geo = col.count_documents({"geometry": {"$geoWithin": {"$geometry": muni["geometry"]}}})
    pct = 100 * by_geo / by_code if by_code else 0
    out["cross_check"] = {"municipality": muni["_id"], "name": muni["name"], "by_code": by_code,
                          "by_geoWithin": by_geo, "pct": round(pct, 2)}
    check("asignación previa vs $geoWithin", pct >= 95,
          f"{muni['name']} ({muni['_id']}): {by_code:,} por código, {by_geo:,} por $geoWithin ({pct:.1f} %); "
          "la diferencia son edificios que cruzan el límite")
    return out


def tex(s):
    return str(s).replace("_", r"\_").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


def write_outputs(result, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "evidence.json", result)
    md = [f"# Evidencia de índices: colecciones de edificios\n",
          f"MongoDB {result['mongo_version']} · base `{result['database']}` · {result['generated_at']}\n"]
    rows = []
    for c in result["collections"]:
        md.append(f"\n## `{c['collection']}` ({c.get('documents', 0):,} documentos)\n")
        md += ["| Control | Resultado | Detalle |", "|---|---|---|"]
        md += [f"| {k['check']} | {'OK' if k['ok'] else 'FALLA'} | {k['detail']} |" for k in c["checks"]]
        md += ["\n| Consulta | Plan | Claves | Docs examinados | Devueltos | ms |", "|---|---|---|---|---|---|"]
        for q in c["queries"]:
            for label, key in (("", "plan_index"), (" (sin índice)", "plan_collscan")):
                p = q.get(key)
                if p:
                    md.append(f"| {q['query']}{label} | {'/'.join(p['stages'])} | {p['keys_examined']} | "
                              f"{p['docs_examined']} | {p['n_returned']} | {p['millis']} |")
            p, cs = q["plan_index"], q.get("plan_collscan")
            rows.append(f"\\texttt{{{tex(c['collection'])}}} & \\texttt{{{tex(q['query'])}}} & {tex('/'.join(p['stages']))} & "
                        f"{p['docs_examined']} & {cs['docs_examined'] if cs and cs.get('docs_examined') is not None else '--'} & "
                        f"{p['millis']} \\\\")
    (out_dir / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / "evidence_table.tex").write_text(
        "\\begin{tabular}{p{0.2\\linewidth}p{0.2\\linewidth}p{0.17\\linewidth}rrr}\n\\toprule\n"
        "Colección & Consulta & Plan & Docs (índice) & Docs (sin índice) & ms \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-collscan", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    from pymongo import MongoClient

    client = MongoClient(cfg["mongo"]["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit("No se pudo conectar a MongoDB (¿docker compose up -d?): " + str(e)[:120])
    db = client[cfg["mongo"]["database"]]
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "mongo_version": client.server_info().get("version"), "database": cfg["mongo"]["database"],
              "collections": [evidence_for(db, cfg["collections"][s], cfg, not a.no_collscan)
                              for s in ("microsoft", "google")]}
    out_dir = repo_path(cfg["evidence"]["out_dir"])
    write_outputs(result, out_dir)
    print(f"\nEvidencia escrita en {out_dir}/")
    return 0 if all(k["ok"] for c in result["collections"] for k in c["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
