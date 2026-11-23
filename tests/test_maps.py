"""Pruebas de los mapas con polígonos y resultados sintéticos (sin MongoDB ni datos reales).

    python -m pytest tests/test_maps.py -q
"""
import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("make_maps", ROOT / "src/05_make_maps.py")
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)

CODES = ["05001", "05002", "05003", "05004"]


def results_long():
    rows = []
    for i, c in enumerate(CODES):
        for s, k in (("microsoft", 1.0), ("google", 0.0 if c == "05004" else 1.3)):
            rows.append({"municipality_code": c, "name": f"M{c}", "source": s, "building_count": int(1000 * k * (i + 1)),
                         "suitable_area_m2": 1e6 * k * (i + 1), "sin_datos": k == 0})
    return pd.DataFrame(rows)


@pytest.fixture
def geoms():
    return gpd.GeoDataFrame({"municipality_code": CODES},
                            geometry=[box(-75 + i, 4, -74.1 + i, 5) for i in range(4)], crs="EPSG:4326")


def test_read_results_long_and_wide(tmp_path):
    results_long().to_csv(tmp_path / "l.csv", index=False)
    df = mm.read_results(tmp_path / "l.csv")
    assert len(df) == 4 and df.municipality_code.iloc[0] == "05001"
    r = df.set_index("municipality_code")
    assert r.loc["05001", "ms_apt_km2"] == pytest.approx(1.0) and r.loc["05001", "ratio_n"] == pytest.approx(1.3)
    assert bool(r.loc["05004", "g_sin_datos"]) and not bool(r.loc["05001", "g_sin_datos"])
    wide = pd.DataFrame({"municipality_code": CODES[:2], "name": ["A", "B"], "ms_n_buildings": [10, 20],
                         "ms_area_apt_m2": [1e6, 2e6], "g_n_buildings": [15, None], "g_area_apt_m2": [1e6, None]})
    wide.to_csv(tmp_path / "w.csv", index=False)
    w = mm.read_results(tmp_path / "w.csv").set_index("municipality_code")
    assert bool(w.loc["05002", "g_sin_datos"]) and w.loc["05001", "diff_km2"] == pytest.approx(0.0)
    pd.DataFrame({"x": [1]}).to_csv(tmp_path / "bad.csv", index=False)
    with pytest.raises(ValueError):
        mm.read_results(tmp_path / "bad.csv")


def test_load_geometries_normalizes_code_column(tmp_path, geoms):
    g = geoms.rename(columns={"municipality_code": "divipola"})
    g["divipola"] = ["5001", "5002", "5003", "5004"]                    # sin cero inicial
    g.to_file(tmp_path / "m.geojson", driver="GeoJSON")
    out = mm.load_geometries(tmp_path / "m.geojson")
    assert list(out.municipality_code) == CODES
    g.rename(columns={"divipola": "otra"}).to_file(tmp_path / "x.geojson", driver="GeoJSON")
    with pytest.raises(ValueError):
        mm.load_geometries(tmp_path / "x.geojson")


def test_make_all_writes_four_figures_with_hatched_missing(tmp_path, geoms):
    cfg = {"attribution": "Datos de prueba", "dpi": 60, "top_n": 3}
    results_long().to_csv(tmp_path / "l.csv", index=False)
    names = mm.make_all(mm.read_results(tmp_path / "l.csv"), geoms, tmp_path / "out", cfg)
    assert names == ["mapa_area_apta.png", "mapa_diferencia.png", "mapa_razon_conteo.png", "top_area_apta.png"]
    for n in names:
        assert (tmp_path / "out" / n).stat().st_size > 2000


def test_municipality_without_polygon_is_reported(tmp_path, geoms, capsys):
    df = mm.read_results(_write(tmp_path, results_long()))
    mm.make_all(df, geoms.iloc[:3], tmp_path / "o", {"attribution": "x", "dpi": 50, "top_n": 2})
    assert "no tienen polígono" in capsys.readouterr().out


def _write(tmp, df):
    df.to_csv(tmp / "r.csv", index=False)
    return tmp / "r.csv"
