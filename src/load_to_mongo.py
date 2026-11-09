#!/usr/bin/env python3
"""Carga los municipios PDET (GeoJSON limpio) en MongoDB, crea los índices espaciales y registra la carga.

Uso:
    python src/load_to_mongo.py                       # lee la ruta de config/spatial.yaml
    python src/load_to_mongo.py --input data/processed/pdet_municipios.geojson
    python src/load_to_mongo.py --dry-run             # solo valida, no toca la base
    python src/load_to_mongo.py --drop                # vacía la colección antes de cargar
Es idempotente: cada municipio se inserta con upsert por _id (código DIVIPOLA).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdet_mongo import REPO_ROOT, build_document, load_params, sha256_file  # noqa: E402


def read_features(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        return data["features"]
    if data.get("type") == "Feature":
        return [data]
    raise SystemExit(f"{path} no es un GeoJSON FeatureCollection")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--repair", action="store_true", help="repara geometrías inválidas con make_valid")
    args = ap.parse_args()

    cfg = load_params()
    path = args.input or cfg["input"]["municipalities_geojson"]
    path = Path(path) if Path(path).is_absolute() else Path.cwd() / path
    if not path.exists():
        path = REPO_ROOT / (args.input or cfg["input"]["municipalities_geojson"])
    features = read_features(path)

    docs, rejected = [], []
    seen = set()
    for i, feat in enumerate(features):
        try:
            doc, note = build_document(feat, cfg, repair=args.repair)
            if doc["_id"] in seen:
                raise ValueError(f"código duplicado {doc['_id']}")
            seen.add(doc["_id"])
            docs.append(doc)
            if note:
                print(f"[aviso] {doc['_id']} {doc['name']}: {note}")
        except ValueError as e:
            rejected.append({"feature_index": i, "error": str(e)})
            print(f"[rechazado] feature {i}: {e}")

    print(f"Leídos: {len(features)} | válidos: {len(docs)} | rechazados: {len(rejected)}")
    exp = cfg["validation"]["expected_municipalities"]
    subs = {d["pdet_subregion"] for d in docs}
    print(f"Municipios: {len(docs)} (esperados {exp}) | subregiones: {len(subs)} "
          f"(esperadas {cfg['validation']['expected_subregions']})")
    if args.dry_run:
        return 0 if not rejected else 1

    from pymongo import ASCENDING, GEOSPHERE, MongoClient, errors
    client = MongoClient(cfg["mongo"]["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit("No se pudo conectar a MongoDB (¿docker compose up -d?): " + str(e)[:120])
    db = client[cfg["mongo"]["database"]]
    col = db[cfg["collections"]["municipalities"]]
    if args.drop:
        col.drop()

    # Índices ANTES de insertar: MongoDB rechaza cualquier geometría que no pueda indexar (validación extra)
    col.create_index([("geometry", GEOSPHERE)], name="geometry_2dsphere")
    col.create_index([("pdet_subregion", ASCENDING)], name="pdet_subregion_1")

    inserted = 0
    for d in docs:
        try:
            col.replace_one({"_id": d["_id"]}, d, upsert=True)
            inserted += 1
        except errors.PyMongoError as e:
            rejected.append({"_id": d["_id"], "error": f"MongoDB: {str(e)[:200]}"})
            print(f"[rechazado por MongoDB] {d['_id']} {d['name']}: {str(e)[:200]}")

    db[cfg["collections"]["ingestion_log"]].insert_one({
        "collection": cfg["collections"]["municipalities"],
        "file": str(path),
        "rows_read": len(features),
        "rows_inserted": inserted,
        "rows_rejected": len(rejected),
        "rejected": rejected[:50],
        "checksum": sha256_file(path),
        "mgn_version": cfg["input"]["mgn_version"],
        "loaded_at": datetime.now(timezone.utc),
    })
    print(f"Insertados/actualizados: {inserted} | en la colección: {col.count_documents({})}")
    print("Índices:", [ix["name"] for ix in col.list_indexes()])
    return 0 if not rejected else 1


if __name__ == "__main__":
    sys.exit(main())
