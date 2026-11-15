"""Pruebas de las tablas, figuras y salidas del EDA y de la evidencia (sin MongoDB)."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eda_tables_and_figures(tmp_path):
    eda = load_script("buildings_eda", "buildings_eda.py")
    ms = pd.DataFrame({"municipality_code": ["05001", "05002"], "n_buildings": [100, 50], "area_total_m2": [1e4, 5e3],
                       "area_mean_m2": [100, 100], "n_apt": [90, 40], "area_apt_m2": [9e3, 4e3]})
    gg = pd.DataFrame({"municipality_code": ["05001", "05003"], "n_buildings": [120, 10], "area_total_m2": [1.1e4, 1e3],
                       "area_mean_m2": [90, 100], "n_apt": [80, 5], "area_apt_m2": [8e3, 500]})
    names = pd.DataFrame({"municipality_code": ["05001", "05002", "05003"], "name": ["A", "B", "C"]})
    comb = eda.combine(ms, gg, names)
    assert len(comb) == 3 and comb.loc[comb.municipality_code == "05003", "ms_n_buildings"].iloc[0] == 0
    assert comb.loc[comb.municipality_code == "05001", "ratio_g_ms"].iloc[0] == pytest.approx(1.2)
    ha = {s: pd.DataFrame({"lower": eda.AREA_BINS[:-1], "n": range(1, 10)}) for s in ("microsoft", "google")}
    hc = pd.DataFrame({"lower": eda.CONF_BINS[:-1], "n": range(1, 10)})
    eda.make_figures(tmp_path, comb, ha, hc)
    for f in ("hist_area.png", "hist_confianza_google.png", "scatter_municipios.png", "top15_area_apta.png"):
        assert (tmp_path / f).stat().st_size > 1000
    table = eda.summary_table({"microsoft": {"n": 150, "mean": 100.0, "total": 15000.0},
                               "google": {"n": 130, "mean": 91.0, "median": 60.0, "p99": 500.0, "total": 12000.0}},
                              {"microsoft": {"n_apt": 130, "area_apt_m2": 13000.0}, "google": {"n_apt": 85, "area_apt_m2": 8500.0}})
    eda.write_summary(tmp_path, table, {"sample": 10, "with_microsoft_overlap": 8, "pct": 80.0})
    assert "Solapamiento" in (tmp_path / "eda_resumen.md").read_text(encoding="utf-8") and (tmp_path / "eda_resumen.tex").exists()


def test_evidence_outputs(tmp_path):
    ev = load_script("buildings_evidence", "buildings_evidence.py")
    plan = {"stages": ["FETCH", "IXSCAN"], "keys_examined": 3, "docs_examined": 3, "n_returned": 1, "millis": 2,
            "uses_index": True, "collscan": False}
    res = {"generated_at": "x", "mongo_version": "7.0", "database": "d", "collections": [{
        "collection": "buildings_google", "documents": 10, "checks": [{"check": "c", "ok": True, "detail": "d"}],
        "queries": [{"query": "q_1", "plan_index": plan, "plan_collscan": dict(plan, stages=["COLLSCAN"], docs_examined=10)}]}]}
    ev.write_outputs(res, tmp_path)
    assert "IXSCAN" in (tmp_path / "evidence.md").read_text(encoding="utf-8")
    assert "q\\_1" in (tmp_path / "evidence_table.tex").read_text(encoding="utf-8")
