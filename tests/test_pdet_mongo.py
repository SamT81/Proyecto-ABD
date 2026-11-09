"""Pruebas que no requieren MongoDB. Ejecutar:  python -m pytest tests/ -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pdet_mongo import build_document, normalize_geometry, summarize_explain  # noqa: E402

CFG = {"validation": {"bbox": [-82, -5, -66, 14]}, "input": {"mgn_version": "MGN2025"}}
BBOX = CFG["validation"]["bbox"]
# cuadrado de ~11 km al norte de Antioquia, anillo HORARIO (hay que reorientarlo)
CW = [[-76.7, 7.8], [-76.7, 7.9], [-76.6, 7.9], [-76.6, 7.8], [-76.7, 7.8]]


def feat(code="05045", geom=None, **extra):
    props = {"MPIO_CDPMP": code, "MPIO_CNMBR": "Apartadó", "DPTO_CNMBR": "Antioquia",
             "subregion": "Urabá antioqueño"}
    props.update(extra)
    return {"type": "Feature", "properties": props,
            "geometry": geom or {"type": "Polygon", "coordinates": [CW]}}


def test_polygon_becomes_multipolygon_counterclockwise():
    g, _ = normalize_geometry({"type": "Polygon", "coordinates": [CW]}, BBOX)
    ring = g["coordinates"][0][0]
    area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))
    assert g["type"] == "MultiPolygon" and area2 > 0


def test_invalid_bowtie_rejected_and_repaired():
    bow = {"type": "Polygon", "coordinates": [[[-76.7, 7.8], [-76.6, 7.9], [-76.6, 7.8], [-76.7, 7.9], [-76.7, 7.8]]]}
    with pytest.raises(ValueError, match="inválida"):
        normalize_geometry(bow, BBOX)
    g, note = normalize_geometry(bow, BBOX, repair=True)
    assert g["type"] == "MultiPolygon" and "reparada" in note


def test_swapped_and_projected_coordinates_rejected():
    swapped = {"type": "Polygon", "coordinates": [[[y, x] for x, y in CW]]}
    with pytest.raises(ValueError, match="caja de Colombia"):
        normalize_geometry(swapped, BBOX)
    meters = {"type": "Polygon", "coordinates": [[[4800000, 2100000], [4800100, 2100000],
                                                  [4800100, 2100100], [4800000, 2100000]]]}
    with pytest.raises(ValueError):
        normalize_geometry(meters, BBOX)


def test_document_fields_and_code_padding():
    doc, _ = build_document(feat(code="5045"), CFG)
    assert doc["_id"] == "05045" and doc["department_code"] == "05"
    assert doc["name"] == "Apartadó" and doc["pdet_subregion"] == "Urabá antioqueño"
    assert doc["geometry"]["type"] == "MultiPolygon" and doc["mgn_version"] == "MGN2025"
    assert 100 < doc["area_km2"] < 130          # ~0.1° x 0.1° cerca de 8°N ≈ 122 km²


def test_bad_codes_and_missing_fields():
    with pytest.raises(ValueError):
        build_document(feat(code="ABC12"), CFG)
    f = feat()
    del f["properties"]["subregion"]
    with pytest.raises(ValueError, match="subregión"):
        build_document(f, CFG)


def test_summarize_explain_ixscan_and_collscan():
    ix = {"queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {
        "stage": "IXSCAN", "indexName": "geometry_2dsphere"}}},
        "executionStats": {"totalKeysExamined": 4, "totalDocsExamined": 3, "nReturned": 1,
                           "executionTimeMillis": 1}}
    s = summarize_explain(ix)
    assert s["uses_index"] and not s["collscan"] and s["index_used"] == "geometry_2dsphere"
    cs = {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}},
          "executionStats": {"totalDocsExamined": 170, "nReturned": 1}}
    assert summarize_explain(cs)["collscan"] and not summarize_explain(cs)["uses_index"]
