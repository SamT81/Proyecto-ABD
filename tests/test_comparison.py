"""Pruebas de la comparación entre fuentes con datos sintéticos (sin MongoDB).

    python -m pytest tests/test_comparison.py -q
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("compare_sources", ROOT / "src/04_compare_sources.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

CFG = {"top_n": 2, "ranking_n": 3, "concordance_top_k": 2, "min_buildings_relative": 100}


def long_df():
    rows = []
    data = {  # código: (ms_n, ms_apt_m2, g_n, g_apt_m2)
        "00001": (1000, 4e6, 2000, 3e6), "00002": (500, 1e6, 900, 1.2e6), "00003": (200, 5e5, 150, 4e5),
        "00004": (300, 2e6, 0, 0)}                                          # Google sin datos
    for code, (mn, ma, gn, ga) in data.items():
        for s, n, a in (("microsoft", mn, ma), ("google", gn, ga)):
            rows.append({"municipality_code": code, "name": f"M{code}", "pdet_subregion": "S1" if code < "00003" else "S2",
                         "source": s, "building_count": n, "total_roof_area_m2": a * 1.1, "suitable_count": n,
                         "suitable_area_m2": a, "sin_datos": n == 0})
    return pd.DataFrame(rows)


def test_compare_pivots_and_flags_missing_google():
    c = cs.compare(long_df()).set_index("municipality_code")
    assert c.loc["00001", "diff_count"] == 1000 and c.loc["00001", "ratio_g_ms_count"] == 2.0
    assert c.loc["00001", "diff_apt_km2"] == pytest.approx(-1.0)
    assert c.loc["00001", "rel_diff_apt"] == pytest.approx(-0.25)
    assert c.loc["00004", "g_sin_datos"] and not c.loc["00001", "g_sin_datos"]
    assert c.loc["00001", "ms_rank_apt"] == 1 and c.loc["00004", "ms_rank_apt"] == 2


def test_summary_excludes_municipalities_without_google_data():
    c = cs.compare(long_df())
    s = cs.summarize(c, CFG)
    assert s["municipios"] == 4 and s["municipios_comparables"] == 3
    assert s["municipios_sin_datos_google"] == ["00004"]
    assert s["microsoft"]["edificios"] == 2000 and s["google"]["edificios"] == 3050
    assert 0.5 < s["correlacion"]["area_apta_pearson"] <= 1
    assert s["razon_google_microsoft"]["municipios_google_mayor_conteo"] == 2
    assert s["concordancia_ranking"]["k"] == 2


def test_top_discrepancies_sorted_and_without_missing():
    c = cs.compare(long_df())
    absolute, relative = cs.top_discrepancies(c, CFG)
    assert absolute.iloc[0].municipality_code == "00001" and "00004" not in set(absolute.municipality_code)
    assert set(relative.municipality_code) <= {"00001", "00002", "00003"} and len(relative) <= 2
    assert (relative.ms_building_count >= 100).all()


def test_reads_wide_eda_csv_and_long_results(tmp_path):
    wide = pd.DataFrame({"municipality_code": ["05031", "05040"], "name": ["A", "B"], "pdet_subregion": ["S", "S"],
                         "ms_n_buildings": [10, 20], "ms_area_total_m2": [1e3, 2e3], "ms_n_apt": [9, 18],
                         "ms_area_apt_m2": [900, 1800], "g_n_buildings": [5, None], "g_area_total_m2": [500, None],
                         "g_n_apt": [4, None], "g_area_apt_m2": [450, None]})
    wide.to_csv(tmp_path / "w.csv", index=False)
    long = cs.read_results(tmp_path / "w.csv")
    assert len(long) == 4 and long[(long.municipality_code == "05040") & (long.source == "google")].sin_datos.iloc[0]
    assert long.municipality_code.iloc[0] == "05031"                        # conserva el cero inicial
    long_df().to_csv(tmp_path / "l.csv", index=False)
    assert len(cs.read_results(tmp_path / "l.csv")) == 8
    pd.DataFrame({"x": [1]}).to_csv(tmp_path / "bad.csv", index=False)
    with pytest.raises(ValueError):
        cs.read_results(tmp_path / "bad.csv")


def test_outputs_written_with_integer_counts_in_tex(tmp_path):
    c = cs.compare(long_df())
    absolute, relative = cs.top_discrepancies(c, CFG)
    rm, rg = cs.ranking(c, CFG)
    cs.write_outputs(tmp_path, c, cs.summarize(c, CFG), absolute, relative, rm, rg, cs.by_subregion(c))
    for f in ("comparacion_municipios.csv", "resumen_comparacion.json", "top_discrepancias_abs.tex",
              "ranking_area_apta.tex", "comparacion.md", "por_subregion.csv"):
        assert (tmp_path / f).stat().st_size > 0
    tex = (tmp_path / "top_discrepancias_abs.tex").read_text(encoding="utf-8")
    assert "1\\,000" in tex and "1\\,000.00" not in tex


def test_tex_escape():
    assert cs.tex_escape("A_B & 5%") == r"A\_B \& 5\%"
