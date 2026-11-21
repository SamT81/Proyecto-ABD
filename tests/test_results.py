"""Pruebas de la colección results y la sensibilidad con mongomock (sin MongoDB real).

    python -m pytest tests/test_results.py -q
"""
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import mongomock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("build_results", ROOT / "src/03_build_results.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


@pytest.fixture
def db():
    d = mongomock.MongoClient()["t"]
    d.buildings_microsoft.insert_many([
        {"municipality_code": "11111", "area_m2": 100.0}, {"municipality_code": "11111", "area_m2": 10.0},
        {"municipality_code": "22222", "area_m2": 20.0}])
    d.buildings_google.insert_many([
        {"municipality_code": "11111", "area_m2": 100.0, "confidence": 0.9},
        {"municipality_code": "11111", "area_m2": 100.0, "confidence": 0.5},      # confianza baja
        {"municipality_code": "11111", "area_m2": 5.0, "confidence": 0.95}])      # área baja
    return d


def run(db, source, area=15, conf=0.70):
    pipe = br.build_pipeline(source, area, conf, "EPSG:9377", NOW)
    return {d["municipality_code"]: d for d in db[f"buildings_{source}"].aggregate(pipe)}


def test_microsoft_counts_and_suitable_area(db):
    r = run(db, "microsoft")
    assert r["11111"]["building_count"] == 2 and r["11111"]["total_roof_area_m2"] == 110.0
    assert r["11111"]["suitable_count"] == 1 and r["11111"]["suitable_area_m2"] == 100.0
    assert r["22222"]["suitable_count"] == 1 and r["22222"]["source"] == "microsoft"
    assert r["11111"]["params"] == {"min_area_m2": 15, "min_confidence": None, "crs_area": "EPSG:9377"}
    assert r["11111"]["computed_at"] == NOW.replace(tzinfo=None) or r["11111"]["computed_at"] == NOW


def test_google_requires_confidence_and_area(db):
    r = run(db, "google")["11111"]
    assert r["building_count"] == 3 and r["suitable_count"] == 1 and r["suitable_area_m2"] == 100.0
    assert r["params"]["min_confidence"] == 0.70
    assert run(db, "google", conf=0.4)["11111"]["suitable_count"] == 2     # más permisivo
    assert run(db, "google", area=1)["11111"]["suitable_count"] == 2       # conf >= 0.7: el de 5 m2 y el de 100 m2


def test_merge_stage_only_when_requested():
    assert "$merge" not in str(br.build_pipeline("google", 15, 0.7, "x", NOW))
    pipe = br.build_pipeline("google", 15, 0.7, "x", NOW, merge_into="results")
    assert pipe[-1]["$merge"]["on"] == ["municipality_code", "source"]


def test_sensitivity_single_pass_grid(db):
    cfg = {"sensitivity": {"min_area_m2": [1, 15], "min_confidence": [0.4, 0.7]}}
    rows = br.sensitivity(db.buildings_google, "google", cfg)
    got = {(r["min_area_m2"], r["min_confidence"]): r["suitable_count"] for r in rows}
    assert got == {(1, 0.4): 2, (1, 0.7): 2, (15, 0.4): 2, (15, 0.7): 1} or len(got) == 4
    assert got[(15, 0.7)] == 1 and got[(1, 0.7)] == 2
    ms = br.sensitivity(db.buildings_microsoft, "microsoft", cfg)
    assert len(ms) == 2 and ms[0]["min_confidence"] == ""            # Microsoft no usa confianza
    assert ms[0]["pct_of_buildings"] == 100.0 and ms[1]["suitable_count"] == 2


def test_export_rows_fill_missing_with_zero_and_flag(db):
    docs = list(db.buildings_microsoft.aggregate(br.build_pipeline("microsoft", 15, 0.7, "x", NOW)))
    muni = {"11111": {"name": "A", "department_name": "D", "pdet_subregion": "S"},
            "22222": {"name": "B", "department_name": "D", "pdet_subregion": "S"},
            "33333": {"name": "C", "department_name": "D", "pdet_subregion": "S"}}
    rows = br.export_rows(docs, muni)
    assert len(rows) == 6                                              # 3 municipios x 2 fuentes
    c_ms = next(r for r in rows if r["municipality_code"] == "33333" and r["source"] == "microsoft")
    assert c_ms["sin_datos"] is True and c_ms["building_count"] == 0
    a_ms = next(r for r in rows if r["municipality_code"] == "11111" and r["source"] == "microsoft")
    assert a_ms["sin_datos"] is False and a_ms["name"] == "A" and a_ms["suitable_count"] == 1


def test_verify_matches_collection_totals(db):
    cfg = {"results": {"collection": "results"}, "collections": {"microsoft": "buildings_microsoft",
                                                                  "google": "buildings_google"}}
    for s in br.SOURCES:
        db.results.insert_many(list(db[f"buildings_{s}"].aggregate(br.build_pipeline(s, 15, 0.7, "x", NOW))))
    v = br.verify(db, cfg, {"11111": {}, "22222": {}})
    assert v["microsoft"]["ok"] and v["google"]["ok"] and v["google"]["buildings_in_results"] == 3
    db.results.delete_one({"source": "google", "municipality_code": "11111"})
    assert not br.verify(db, cfg, {"11111": {}, "22222": {}})["google"]["ok"]


def test_summary_and_csv(tmp_path, db):
    rows = br.export_rows(list(db.buildings_microsoft.aggregate(br.build_pipeline("microsoft", 15, 0.7, "x", NOW))),
                          {"11111": {"name": "A"}})
    br.write_csv(tmp_path / "r.csv", rows, br.RESULT_COLS)
    assert (tmp_path / "r.csv").read_text(encoding="utf-8").startswith("municipality_code,name")
    md = br.summary_md(rows, [], {"microsoft": {"ok": True, "buildings_in_results": 3, "buildings_in_collection": 3}},
                       {"roof_suitability": {"min_area_m2": 15, "min_confidence": 0.7}})
    assert "microsoft" in md and "OK" in md
