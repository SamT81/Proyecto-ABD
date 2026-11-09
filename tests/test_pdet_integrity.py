"""Pruebas unitarias para el módulo de integridad geométrica y el ETL PDET."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.geo_integrity import (  # noqa: E402
    build_municipality_document,
    normalize_divipola,
    prepare_municipalities_gdf,
    repair_and_to_multipolygon,
)


class TestGeoIntegrity(unittest.TestCase):
    def test_normalize_divipola(self) -> None:
        self.assertEqual(normalize_divipola("5045"), "05045")
        self.assertEqual(normalize_divipola(5045), "05045")
        self.assertEqual(normalize_divipola("19001.0"), "19001")
        with self.assertRaises(ValueError):
            normalize_divipola("ABC12")

    def test_repair_bowtie_polygon_to_multipolygon(self) -> None:
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
        self.assertFalse(bowtie.is_valid)
        fixed = repair_and_to_multipolygon(bowtie)
        self.assertIsNotNone(fixed)
        self.assertTrue(fixed.is_valid)
        self.assertEqual(fixed.geom_type, "MultiPolygon")

    def test_prepare_and_build_document_in_colombia(self) -> None:
        poly_apartado = Polygon([
            (-76.65, 7.85),
            (-76.60, 7.85),
            (-76.60, 7.90),
            (-76.65, 7.90),
            (-76.65, 7.85),
        ])
        gdf = gpd.GeoDataFrame(
            {
                "divipola": ["5045"],
                "name": ["APARTADÓ"],
                "department_name": ["ANTIOQUIA"],
                "pdet_subregion": ["URABÁ ANTIOQUEÑO"],
            },
            geometry=[poly_apartado],
            crs="EPSG:4326",
        )
        clean_gdf, rejected = prepare_municipalities_gdf(gdf)
        self.assertEqual(rejected, 0)
        self.assertEqual(len(clean_gdf), 1)
        self.assertGreater(clean_gdf.iloc[0]["area_km2"], 0)

        doc = build_municipality_document(clean_gdf.iloc[0])
        self.assertEqual(doc["_id"], "05045")
        self.assertEqual(doc["department_code"], "05")
        self.assertEqual(doc["geometry"]["type"], "MultiPolygon")
        self.assertLess(len(json.dumps(doc)), 15_500_000)


if __name__ == "__main__":
    unittest.main()
