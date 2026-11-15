"""Pruebas de la carga de edificios con GeoParquet sintético y mongomock (sin MongoDB real).

    python -m pytest tests/test_buildings_load.py -q
"""
import importlib.util
import json
import sys
from pathlib import Path

import geopandas as gpd
import mongomock
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("load_buildings", ROOT / "src/02_load_buildings.py")
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)


def make_partition(base, source, pid, rows, row_group=4, sha="abc"):
    """rows: lista de (municipality_code, area_m2). Escribe part-00000.parquet y _SUCCESS.json."""
    d = Path(base) / source / pid
    d.mkdir(parents=True)
    geoms = [box(-74 + i * 1e-4, 4, -74 + i * 1e-4 + 5e-5, 4 + 5e-5) for i in range(len(rows))]
    data = {"area_m2": [r[1] for r in rows], "municipality_code": [r[0] for r in rows],
            "source_file": [f"{pid}.gz"] * len(rows), "is_valid_geom": [True] * len(rows)}
    if source == "google":
        data.update({"confidence": [0.8] * len(rows), "full_plus_code": ["67P+X"] * len(rows)})
    gpd.GeoDataFrame(data, geometry=geoms, crs="EPSG:4326").to_parquet(
        d / "part-00000.parquet", index=False, row_group_size=row_group)
    per = {}
    for code, _ in rows:
        per[code] = per.get(code, 0) + 1
    (d / "_SUCCESS.json").write_text(json.dumps({
        "source": source, "partition_id": pid, "archivo": f"{pid}.gz", "sha256_entrada": sha,
        "leidos": len(rows) * 3, "fuera_pdet": len(rows) * 2, "escritos": len(rows), "por_municipio": per}))
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    client = mongomock.MongoClient()
    monkeypatch.setattr(lb, "_db", lambda cfg: (client, client["t"]))
    monkeypatch.setattr(lb, "ROOT", tmp_path)
    cfg = {"mongo": {"uri": "x", "database": "t"}, "load": {"workers": 1, "batch_size": 3},
           "input": {"processed_dir": "proc"},
           "collections": {"microsoft": "buildings_microsoft", "google": "buildings_google",
                           "ingestion_log": "ingestion_log"},
           "indexes": {"compound": [["municipality_code", 1], ["area_m2", -1]], "google_confidence": True},
           "benchmark": {"batch_sizes": [2, 5], "sample_docs": 6},
           "output": {"metrics_json": "m.json", "metrics_md": "m.md"}}
    proc = tmp_path / "proc"
    make_partition(proc, "google", "8e1", [("11111", 20.0)] * 3 + [("22222", 30.0)] * 4)
    make_partition(proc, "google", "8e3", [("11111", 25.0)] * 2)
    return cfg, client["t"]


def parts(cfg, source="google"):
    return lb.discover(source, cfg)


def test_discover_orders_largest_first(env):
    cfg, _ = env
    assert [p["id"] for p in parts(cfg)] == ["8e1", "8e3"]
    assert parts(cfg, "microsoft") == []


def test_load_inserts_logs_and_counts(env):
    cfg, db = env
    p = parts(cfg)[0]
    r = lb.load_partition((cfg, "google", p, False, 3))
    assert r["inserted"] == 7 and r["in_db"] == 7 and r["status"] == "ok"
    doc = db.buildings_google.find_one({"municipality_code": "22222"})
    assert doc["geometry"]["type"] == "Polygon" and doc["confidence"] == 0.8 and doc["source_file"] == "8e1.gz"
    log = db.ingestion_log.find_one({"file": "8e1.gz"})
    assert log["status"] == "ok" and log["checksum"] == "abc" and log["rows_inserted"] == 7


def test_second_run_is_skipped(env):
    cfg, db = env
    p = parts(cfg)[0]
    lb.load_partition((cfg, "google", p, False, 3))
    r = lb.load_partition((cfg, "google", p, False, 3))
    assert r.get("skipped") is True and db.buildings_google.count_documents({}) == 7


def test_resume_cleans_leftovers_of_interrupted_partition(env):
    cfg, db = env
    p = parts(cfg)[0]
    db.buildings_google.insert_many([{"source_file": "8e1.gz", "municipality_code": "99999"} for _ in range(2)])  # sin bitácora
    r = lb.load_partition((cfg, "google", p, False, 3))
    assert r["status"] == "ok" and db.buildings_google.count_documents({}) == 7


def test_changed_input_checksum_reloads(env):
    cfg, db = env
    p = parts(cfg)[0]
    lb.load_partition((cfg, "google", p, False, 3))
    p["info"]["sha256_entrada"] = "otro"
    r = lb.load_partition((cfg, "google", p, False, 3))
    assert not r.get("skipped") and db.buildings_google.count_documents({}) == 7   # reemplazó, no duplicó


def test_mismatch_when_etl_count_differs(env):
    cfg, db = env
    p = parts(cfg)[0]
    p["info"]["escritos"] = 99
    r = lb.load_partition((cfg, "google", p, False, 3))
    assert r["status"] == "mismatch"
    assert db.ingestion_log.find_one({"file": "8e1.gz"})["status"] == "mismatch"


def test_dry_run_writes_nothing(env):
    cfg, db = env
    r = lb.load_partition((cfg, "google", parts(cfg)[0], True, 3))
    assert r["read"] == 7 and "status" not in r
    assert db.buildings_google.count_documents({}) == 0 and db.ingestion_log.count_documents({}) == 0


def test_insert_batches_counts_all(env):
    _, db = env
    ok, bad = lb.insert_batches(db.x, [{"a": i} for i in range(10)], 4)
    assert (ok, bad) == (10, 0) and db.x.count_documents({}) == 10


def test_verify_ok_and_detects_missing_documents(env):
    cfg, db = env
    for p in parts(cfg):
        lb.load_partition((cfg, "google", p, False, 3))
    v = lb.verify("google", cfg)
    assert v["ok"] and v["expected_total"] == 9 and v["municipalities_in_db"] == 2
    db.buildings_google.delete_one({"municipality_code": "22222"})
    v = lb.verify("google", cfg)
    assert not v["ok"] and v["municipalities_with_diff"] == 1


def test_benchmark_runs_each_batch_size(env):
    cfg, db = env
    b = lb.benchmark("google", cfg)
    assert [r["batch_size"] for r in b["results"]] == [2, 5]
    assert all(r["docs"] == 6 for r in b["results"]) and "bench_tmp" not in db.list_collection_names()


def test_write_metrics_creates_json_and_md(env):
    cfg, _ = env
    lb.write_metrics({"workers": 2, "batch_size": 3, "started_at": "a", "finished_at": "b",
                      "sources": {"google": {"totals": {"partitions": 2, "inserted": 9, "seconds": 1.0,
                                                        "docs_per_s": 9.0}, "index_seconds": {"x": 1}}},
                      "verify": {"google": {"expected_total": 9, "in_db_total": 9,
                                            "municipalities_with_diff": 0, "ok": True}}}, cfg)
    assert json.loads((lb.ROOT / "m.json").read_text())["workers"] == 2
    assert "OK" in (lb.ROOT / "m.md").read_text()
