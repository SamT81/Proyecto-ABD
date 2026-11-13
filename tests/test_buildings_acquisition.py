"""Pruebas de la selección y verificación de particiones de edificios (sin red).

    python -m pytest tests/test_buildings_acquisition.py -q
"""
import gzip
import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import buildings_acquisition as ba  # noqa: E402


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), SRC / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pdet_layer():
    return gpd.GeoDataFrame(
        {"mpio_cdpmp": ["05490", "81065"]},
        geometry=[box(-76.9, 8.3, -76.6, 8.6), box(-71.6, 6.8, -71.2, 7.1)],
        crs="EPSG:4326",
    )


# ------------------------------------------------------------------------ quadkeys
def test_quadkey_to_tile():
    assert ba.quadkey_to_tile("0") == (0, 0, 1)
    assert ba.quadkey_to_tile("3") == (1, 1, 1)
    assert ba.quadkey_to_tile("213") == (3, 5, 3)


def test_quadkey_invalido():
    with pytest.raises(ValueError):
        ba.quadkey_to_tile("0124")


def test_quadkey_bounds_cubre_un_edificio_conocido():
    # Edificio en San Andrés tomado de la partición 032203300 del índice de Microsoft
    w, s, e, n = ba.quadkey_bounds("032203300")
    assert w <= -81.356 <= e and s <= 13.344 <= n
    assert e - w == pytest.approx(360 / 2 ** 9)


def test_parse_size_y_tolerancia():
    assert ba.parse_size("615.5KB") == int(615.5 * 1024)
    assert ba.parse_size("4.5MB") == int(4.5 * 1024 ** 2)
    assert ba.parse_size("12B") == 12
    with pytest.raises(ValueError):
        ba.parse_size("4,5 MB")
    # 4.5MB publicado y 4.58 MiB reales: dentro del margen de una décima de MB
    assert 4_800_000 - ba.parse_size("4.5MB") <= 2 * ba.size_tolerance(ba.parse_size("4.5MB"))
    assert ba.size_tolerance(800) == 1


# ------------------------------------------------------------------------ selección
def ms_index():
    url = "https://example.org/RegionName=Colombia/quadkey={q}/part-0.csv.gz"
    rows = [("Colombia", "032212332"), ("Colombia", "032230303"), ("Venezuela", "032212332")]
    return pd.DataFrame([{"Location": loc, "QuadKey": q, "Url": url.format(q=q), "Size": "1.0MB",
                          "UploadDate": "2026-02-23"} for loc, q in rows])


def test_select_microsoft_solo_pais_y_particiones_que_tocan_pdet():
    pdet = pdet_layer()
    cat = ba.select_microsoft(ms_index(), pdet, "Colombia")
    assert list(cat.columns) == ba.CATALOG_COLUMNS
    assert (cat["source"] == "microsoft").all()
    for row in cat.itertuples():
        tile = box(row.west, row.south, row.east, row.north)
        assert tile.intersects(pdet.union_all())
    assert cat["partition_id"].is_unique


def test_select_microsoft_sin_pais():
    with pytest.raises(ValueError):
        ba.select_microsoft(ms_index(), pdet_layer(), "Peru")


def test_select_google_con_md5_del_bucket():
    tiles = gpd.GeoDataFrame({"tile_id": ["8e3", "aaa"], "size_mb": [1.0, 1.0]},
                             geometry=[box(-80, 5, -70, 10), box(10, 10, 20, 20)], crs="EPSG:4326")
    prefix = "v3/polygons_s2_level_4_gzip/"
    objects = [{"name": prefix + "8e3_buildings.csv.gz", "size": "1000000", "md5Hash": "abc=="},
               {"name": prefix + "aaa_buildings.csv.gz", "size": "1000000", "md5Hash": "def=="}]
    cat, missing = ba.select_google(tiles, objects, pdet_layer(), prefix)
    assert missing == []
    assert cat["partition_id"].tolist() == ["8e3"]
    assert cat.loc[0, "md5_b64"] == "abc=="
    assert cat.loc[0, "municipios"] == "05490;81065"
    assert cat.loc[0, "n_municipios"] == 2


def test_check_coverage_detecta_municipio_sin_particion():
    cat = pd.DataFrame({"municipios": ["05490"]})
    qc = ba.QCReport()
    assert ba.check_coverage(cat, ["05490", "81065"], qc, "T-01", "prueba") == ba.FALLA
    assert "81065" in qc.checks[0]["detalle"]


# ------------------------------------------------------------------------ verificación de archivos
def test_md5_y_gzip(tmp_path):
    f = tmp_path / "x.csv.gz"
    with gzip.open(f, "wb") as g:
        g.write(b"a,b\n1,2\n3,4")
    lines, size = ba.gzip_stats(f)
    assert lines == 3 and size == len(b"a,b\n1,2\n3,4")
    assert len(ba.md5_b64(f)) == 24
    assert ba.first_line(f) == "a,b"


def test_gzip_cortado(tmp_path):
    f = tmp_path / "x.csv.gz"
    with gzip.open(f, "wb") as g:
        g.write(b"linea\n" * 50_000)
    data = f.read_bytes()
    f.write_bytes(data[: len(data) // 2])
    with pytest.raises((OSError, EOFError)):
        ba.gzip_stats(f)


def test_formato_primera_linea():
    mod = load_script("00e_download_buildings.py")
    assert mod.check_format("google", mod.GOOGLE_HEADER)[0]
    assert not mod.check_format("google", "lat,lon")[0]
    feat = '{"type": "Feature", "properties": {"height": -1.0}, "geometry": {"type": "Polygon", "coordinates": []}}'
    assert mod.check_format("microsoft", feat)[0]
    assert not mod.check_format("microsoft", "no es json")[0]


def test_write_qc_combina_secciones(tmp_path):
    qj, qm = tmp_path / "qc.json", tmp_path / "qc.md"
    a, b = ba.QCReport(), ba.QCReport()
    a.add("SEL-01", "uno", ba.OK)
    b.add("DL-M1", "dos", ba.AVISO, "detalle | con barra")
    ba.write_qc(qj, qm, "seleccion", a)
    ba.write_qc(qj, qm, "descarga", b)
    md = qm.read_text(encoding="utf-8")
    assert "SEL-01" in md and "DL-M1" in md and "\\|" in md
