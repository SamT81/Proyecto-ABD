"""Pruebas de las funciones de adquisición y control de calidad del MGN (sin red ni MongoDB).

    python -m pytest tests/test_mgn_acquisition.py -q
"""
import importlib.util
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import mgn_acquisition as ma  # noqa: E402


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), SRC / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def art_rows():
    return [
        {"Subregión PDET": "URABÁ ANTIOQUEÑO", "Código DANE Departamento": "5",
         "Departamento": "ANTIOQUIA", "Código DANE Municipio": "5490", "Municipio": "NECOCLÍ"},
        {"Subregión PDET": "URABÁ ANTIOQUEÑO", "Código DANE Departamento": "5",
         "Departamento": "ANTIOQUIA", "Código DANE Municipio": "5837", "Municipio": "TURBO"},
        {"Subregión PDET": "ARAUCA", "Código DANE Departamento": "81",
         "Departamento": "ARAUCA", "Código DANE Municipio": "81065", "Municipio": "ARAUQUITA"},
    ]


def mgn_layer():
    rows = [
        ("05", "490", "05490", "ANTIOQUIA", "NECOCLÍ", box(-76.9, 8.3, -76.6, 8.6)),
        ("05", "837", "05837", "ANTIOQUIA", "TURBO", box(-76.6, 8.0, -76.3, 8.6)),
        ("81", "065", "81065", "ARAUCA", "ARAUQUITA", box(-71.6, 6.7, -71.2, 7.1)),
        ("11", "001", "11001", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.", box(-74.2, 4.5, -74.0, 4.8)),
    ]
    gdf = gpd.GeoDataFrame(rows, columns=["dpto_ccdgo", "mpio_ccdgo", "mpio_cdpmp", "dpto_cnmbr",
                                          "mpio_cnmbr", "geometry"], crs="EPSG:4326")
    gdf["mpio_tipo"] = "MUNICIPIO"
    gdf["mpio_narea"] = gdf.to_crs("EPSG:9377").area / 1e6
    return gdf


CFG = {
    "pdet": {"expected_municipalities": 3, "expected_subregions": 2},
    "qc": {"area_crs": "EPSG:9377", "max_area_diff_pct": 1.0, "max_overlap_km2": 0.01, "max_doc_mb": 15.0},
}


@pytest.mark.parametrize("raw,expected", [(5490, "05490"), ("5490", "05490"), ("05490.0", "05490"),
                                          (" 81065 ", "81065")])
def test_normalize_code(raw, expected):
    assert ma.normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "ABC12", "123456"])
def test_normalize_code_rechaza(raw):
    with pytest.raises(ValueError):
        ma.normalize_code(raw)


def test_normalize_name_ignora_tildes_y_signos():
    assert ma.normalize_name("San Pedro de Urabá") == ma.normalize_name("SAN PEDRO DE URABA")
    assert ma.normalize_name("PIENDAMÓ - TUNÍA") == "PIENDAMO TUNIA"


def test_catalogo_desde_excel():
    cat = ma.catalog_from_rows(art_rows())
    assert list(cat.columns) == ma.CATALOG_COLUMNS
    assert cat["divipola"].tolist() == ["05490", "05837", "81065"]
    assert cat["dpto_ccdgo"].tolist() == ["05", "05", "81"]
    # id alfabético de subregión: ARAUCA=1, URABÁ=2
    assert cat.set_index("divipola")["pdet_subregion_id"].to_dict() == {"05490": 2, "05837": 2, "81065": 1}


def test_catalogo_detecta_duplicados_y_conteo():
    cat = ma.catalog_from_rows(art_rows() + [art_rows()[0]])
    qc = ma.QCReport()
    ma.check_catalog(cat, qc, expected_mpios=3, expected_subregions=2)
    fallidos = {c["id"] for c in qc.failed}
    assert {"PDET-01", "PDET-02"} <= fallidos


def test_capa_mgn_valida():
    qc = ma.QCReport()
    ma.check_mgn_layer(mgn_layer(), qc, "EPSG:4326", 4, [-82, -5, -66, 14])
    assert not qc.failed


def test_capa_mgn_crs_incorrecto():
    qc = ma.QCReport()
    ma.check_mgn_layer(mgn_layer().to_crs("EPSG:9377"), qc, "EPSG:4326", 4, [-82, -5, -66, 14])
    assert {"MGN-02", "MGN-08"} <= {c["id"] for c in qc.failed}


def test_cruce_y_controles_geometricos():
    cat = ma.catalog_from_rows(art_rows())
    qc = ma.QCReport()
    sub = ma.join_catalog(mgn_layer(), cat, qc)
    assert sorted(sub["mpio_cdpmp"]) == ["05490", "05837", "81065"]
    sub = gpd.GeoDataFrame(sub, geometry="geometry", crs="EPSG:4326")
    sub, _ = ma.check_pdet_layer(sub, qc, CFG)
    assert not qc.failed
    assert all(c["resultado"] == ma.OK for c in qc.checks)


def test_cruce_reporta_codigo_faltante():
    rows = art_rows() + [{"Subregión PDET": "ARAUCA", "Código DANE Departamento": "81",
                          "Departamento": "ARAUCA", "Código DANE Municipio": "81300",
                          "Municipio": "FORTUL"}]
    qc = ma.QCReport()
    ma.join_catalog(mgn_layer(), ma.catalog_from_rows(rows), qc)
    join = next(c for c in qc.checks if c["id"] == "JOIN-01")
    assert join["resultado"] == ma.FALLA and "81300" in join["detalle"]


def test_detecta_solape_entre_municipios():
    gdf = mgn_layer()
    gdf.loc[gdf["mpio_cdpmp"] == "05837", "geometry"] = box(-76.7, 8.0, -76.3, 8.6)  # invade NECOCLÍ
    gdf["mpio_narea"] = gdf.to_crs("EPSG:9377").area / 1e6
    qc = ma.QCReport()
    sub = ma.join_catalog(gdf, ma.catalog_from_rows(art_rows()), qc)
    ma.check_pdet_layer(gpd.GeoDataFrame(sub, geometry="geometry", crs="EPSG:4326"), qc, CFG)
    geo8 = next(c for c in qc.checks if c["id"] == "GEO-08")
    assert geo8["resultado"] == ma.AVISO and "05490-05837" in geo8["detalle"]


def test_zip_sin_componentes_del_shapefile(tmp_path):
    dl = load_script("00a_download_mgn.py")
    z = tmp_path / "mgn.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("CAPA.shp", b"x")
        f.writestr("CAPA.dbf", b"x")
    with pytest.raises(SystemExit, match="faltan componentes"):
        dl.check_zip(z, "CAPA.shp")


def test_sha256_conocido(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"abc")
    assert ma.sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_catalogo_versionado_es_coherente():
    """El CSV del repo debe tener los 170 municipios y 16 subregiones."""
    cat = pd.read_csv(SRC.parent / "config/pdet/pdet_municipios.csv", dtype=str)
    qc = ma.QCReport()
    ma.check_catalog(cat, qc)
    assert not qc.failed
