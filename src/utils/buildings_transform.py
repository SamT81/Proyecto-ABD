"""Transformaciones geométricas y normalización de esquema para huellas de edificios (Entrega 3)."""

from __future__ import annotations

import hashlib
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import orient, transform
from shapely.validation import make_valid


def get_area_transformer(src_crs: str = "EPSG:4326", dst_crs: str = "EPSG:9377") -> Transformer:
    """Construye el transformador hacia MAGNA-SIRGAS Origen Nacional (metros)."""
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def build_building_id(source: str, lon: float, lat: float, decimals: int = 7) -> str:
    """Genera un _id determinístico basado en fuente y punto representativo para upserts."""
    key = f"{source}:{round(lon, decimals):.{decimals}f}:{round(lat, decimals):.{decimals}f}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    prefix = "gob" if "google" in source.lower() else "ms"
    return f"{prefix}_{digest}"


def round_coords(obj: Any, decimals: int = 7) -> Any:
    """Redondea recursivamente las coordenadas de una estructura GeoJSON."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(c), decimals) for c in obj]
        return [round_coords(item, decimals) for item in obj]
    return obj


def normalize_building_record(
    geom: BaseGeometry,
    source: str,
    municipality_code: str,
    pdet_subregion: str,
    transformer_to_m: Transformer,
    confidence: float | None = None,
    min_area_m2: float = 15.0,
    decimals: int = 7,
) -> dict[str, Any] | None:
    """Valida, calcula área métrica y estructura un documento de edificio para MongoDB."""
    if geom is None or geom.is_empty:
        return None

    clean_geom = geom if geom.is_valid else make_valid(geom)
    if clean_geom.is_empty or clean_geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None

    if clean_geom.geom_type == "Polygon":
        clean_geom = orient(clean_geom, sign=1.0)

    geom_m = transform(transformer_to_m.transform, clean_geom)
    area_m2 = round(float(geom_m.area), 2)
    if area_m2 <= 0.0:
        return None

    rep_pt = clean_geom.representative_point()
    lon, lat = round(float(rep_pt.x), decimals), round(float(rep_pt.y), decimals)

    geojson_geom = mapping(clean_geom)
    geojson_geom["coordinates"] = round_coords(geojson_geom["coordinates"], decimals)

    return {
        "_id": build_building_id(source, lon, lat, decimals),
        "source": source,
        "municipality_code": str(municipality_code).zfill(5),
        "pdet_subregion": pdet_subregion,
        "area_m2": area_m2,
        "meets_min_area": area_m2 >= min_area_m2,
        "confidence": round(float(confidence), 4) if confidence is not None else None,
        "centroid": {"type": "Point", "coordinates": [lon, lat]},
        "geometry": geojson_geom,
    }
