"""Pruebas del ETL de huellas de edificios con datos sintéticos (sin red ni MongoDB).

    python -m pytest tests/test_buildings_etl.py -q
"""
import gzip
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import buildings_etl as be  # noqa: E402

# Dos municipios vecinos que comparten el borde x = -74.0
MPIOS = gpd.GeoDataFrame({"mpio_cdpmp": ["11111", "22222"]},
                         geometry=[box(-74.2, 4.0, -74.0, 4.2), box(-74.0, 4.0, -73.8, 4.2)], crs="EPSG:4326")


TO_9377 = Transformer.from_crs("EPSG:4326", "EPSG:9377", always_xy=True)


def square(lon, lat, side_m=10.0):
    """Cuadrado de `side_m` metros de lado en EPSG:9377, devuelto en lon/lat."""
    x, y = TO_9377.transform(lon, lat)
    sq = box(x, y, x + side_m, y + side_m)
    return shapely.transform(sq, lambda c: np.column_stack(TO_9377.transform(c[:, 0], c[:, 1],
                                                                              direction="INVERSE")))


@pytest.fixture
def pdet():
    return be.PdetIndex.from_gdf(MPIOS, prefilter_deg=0.002)


# ------------------------------------------------------------------------ asignación
def test_assign_por_municipio_y_fuera(pdet):
    idx = pdet.assign([-74.1, -73.9, -75.0], [4.1, 4.1, 4.1])
    assert pdet.codes[idx[0]] == "11111"
    assert pdet.codes[idx[1]] == "22222"
    assert idx[2] == -1


def test_assign_borde_compartido_una_sola_vez(pdet):
    idx = pdet.assign([-74.0], [4.1])
    assert idx[0] in (0, 1)


def test_near_usa_margen(pdet):
    # A 0.001° del borde exterior: fuera del municipio pero dentro del margen de prefiltro
    assert pdet.assign([-74.201], [4.1])[0] == -1
    assert pdet.near(np.array([-74.201, -74.5]), np.array([4.1, 4.1])).tolist() == [True, False]


def test_pdet_index_exige_wgs84():
    with pytest.raises(ValueError):
        be.PdetIndex.from_gdf(MPIOS.to_crs("EPSG:9377"))


# ------------------------------------------------------------------------ geometría
def test_clean_repara_corbatin_y_reduce_a_polygon():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    geoms, valid, reason, multi = be.clean_geometries([bowtie, box(0, 0, 1, 1), None])
    assert reason.tolist() == ["", "", "vacía o ilegible"]
    assert valid.tolist()[:2] == [False, True]
    assert multi[0]                       # make_valid devuelve dos triángulos
    assert geoms[0].geom_type == "Polygon" and geoms[0].is_valid
    assert geoms[2] is None


def test_round_orienta_y_redondea():
    cw = Polygon([(0, 0), (0, 1e-4), (1e-4, 1e-4), (1e-4, 0)])   # anillo exterior horario
    out, ok = be.round_geometries([cw], precision=6)
    assert ok[0]
    assert shapely.is_ccw(out[0].exterior)
    xs = np.array(out[0].exterior.coords).ravel()
    assert np.allclose(xs, np.round(xs, 6))


def test_round_colapsa_edificio_menor_que_la_grilla():
    tiny = box(0, 0, 1e-8, 1e-8)
    out, ok = be.round_geometries([tiny], precision=6)
    assert not ok[0] and out[0] is None


def test_area_en_9377():
    area = be.make_area_fn("EPSG:9377")([square(-74.1, 4.1, 10.0)])[0]
    assert area == pytest.approx(100.0, rel=0.01)


# ------------------------------------------------------------------------ bloques
def google_df():
    geoms = [square(-74.1, 4.1), square(-73.9, 4.1), square(-75.0, 4.1)]
    return pd.DataFrame({
        "latitude": [4.1, 4.1, 4.1], "longitude": [-74.1, -73.9, -75.0],
        "area_in_meters": [100.0, 100.0, 100.0], "confidence": [0.9, 0.65, 0.8],
        "geometry": geoms, "full_plus_code": ["A", "B", "C"],
    })


def test_transform_chunk_google(pdet):
    out, stats, sample = be.transform_chunk(google_df(), "google", "8e1_buildings.csv.gz", pdet,
                                            be.make_area_fn("EPSG:9377"))
    assert list(out.columns) == be.OUTPUT_COLUMNS["google"]
    assert out["municipality_code"].tolist() == ["11111", "22222"]
    assert out["area_m2"].tolist() == [100.0, 100.0]       # se conserva area_in_meters
    assert stats["fuera_pdet"] == 1 and stats["escritos"] == 2
    assert np.all(np.abs(sample) < 0.02)


def test_transform_chunk_microsoft_calcula_area(pdet):
    df = pd.DataFrame({"geometry": [square(-74.1, 4.1, 20.0)]})
    out, stats, _ = be.transform_chunk(df, "microsoft", "q.csv.gz", pdet, be.make_area_fn("EPSG:9377"))
    assert list(out.columns) == be.OUTPUT_COLUMNS["microsoft"]
    assert out.loc[0, "area_m2"] == pytest.approx(400.0, rel=0.01)
    assert bool(out.loc[0, "is_valid_geom"])


def test_transform_chunk_rechazo_dentro_de_pdet(pdet):
    df = pd.DataFrame({"geometry": [None, square(-74.1, 4.1)]})
    _, stats, _ = be.transform_chunk(df, "microsoft", "q.csv.gz", pdet, be.make_area_fn("EPSG:9377"))
    # Una geometría nula no se puede ubicar: cuenta como fuera de PDET, no como rechazo
    assert stats["fuera_pdet"] == 1 and stats["escritos"] == 1


def test_readers(tmp_path):
    ms = tmp_path / "q.csv.gz"
    feat = {"type": "Feature", "properties": {"height": -1.0, "confidence": -1.0},
            "geometry": shapely.geometry.mapping(square(-74.1, 4.1))}
    with gzip.open(ms, "wt", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(feat) for _ in range(5)) + "\n")
    chunks = list(be.read_microsoft(ms, chunk_rows=2))
    assert [n for n, _ in chunks] == [2, 2, 1]

    gg = tmp_path / "g.csv.gz"
    df = google_df()
    df["geometry"] = shapely.to_wkt(df["geometry"].to_numpy())
    df.to_csv(gg, index=False, compression="gzip")
    keep = lambda x, y: x > -74.5  # noqa: E731
    (n, out), = list(be.read_google(gg, chunk_rows=10, keep=keep))
    assert n == 3 and len(out) == 2 and out.loc[0, "geometry"].geom_type == "Polygon"


def test_process_partition_escribe_geoparquet(tmp_path):
    gpkg = tmp_path / "pdet.gpkg"
    MPIOS.to_file(gpkg, layer="municipios_pdet")
    raw = tmp_path / "8e1_buildings.csv.gz"
    df = google_df()
    df["geometry"] = shapely.to_wkt(df["geometry"].to_numpy())
    df.to_csv(raw, index=False, compression="gzip")
    out_dir = tmp_path / "out" / "google" / "8e1"
    task = {"source": "google", "partition_id": "8e1", "raw_file": str(raw), "sha256": "x",
            "municipios": ["11111", "22222"], "out_dir": str(out_dir), "pdet_gpkg": str(gpkg),
            "pdet_layer": "municipios_pdet", "area_crs": "EPSG:9377", "chunk_rows": 2,
            "row_group_size": 10, "precision": 6, "prefilter_deg": 0.002}
    s = be.process_partition(task)
    assert s["leidos"] == 3 and s["escritos"] == 2 and s["fuera_pdet"] == 1
    assert s["por_municipio"] == {"11111": 1, "22222": 1}
    assert (out_dir / "_SUCCESS.json").exists() and not out_dir.with_name("8e1.tmp").exists()
    back = gpd.read_parquet(out_dir)
    assert len(back) == 2 and back.crs.to_epsg() == 4326
    assert set(back["source_file"]) == {"8e1_buildings.csv.gz"}

    docs = [d for lote in be.iter_documents(out_dir) for d in lote]
    assert len(docs) == 2
    assert docs[0]["geometry"]["type"] == "Polygon"
    assert set(docs[0]) == set(be.OUTPUT_COLUMNS["google"])
    assert isinstance(docs[0]["is_valid_geom"], bool)
