"""Funciones de integridad geométrica, reproyección y formateo para MongoDB."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.polygon import orient
from shapely.validation import make_valid

COLOMBIA_BBOX = (-82.0, -5.0, -66.0, 14.0)


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calcula el hash SHA-256 de un archivo leyendo por bloques."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_divipola(code: Any) -> str:
    """Normaliza un código municipal DIVIPOLA a cadena de 5 dígitos con ceros a la izquierda."""
    cleaned = str(code).strip().split(".")[0]
    if not cleaned.isdigit() or len(cleaned) > 5:
        raise ValueError(f"Código DIVIPOLA inválido: {code!r}")
    return cleaned.zfill(5)


def repair_and_to_multipolygon(geom: Any) -> MultiPolygon | None:
    """Repara geometrías inválidas, orienta anillos (mano derecha) y devuelve MultiPolygon."""
    if geom is None or geom.is_empty:
        return None

    if not geom.is_valid:
        geom = make_valid(geom)

    if geom.is_empty:
        return None

    parts: list[Polygon] = []
    if isinstance(geom, Polygon):
        parts = [geom]
    elif isinstance(geom, MultiPolygon):
        parts = list(geom.geoms)
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            if isinstance(g, Polygon) and not g.is_empty:
                parts.append(g)
            elif isinstance(g, MultiPolygon) and not g.is_empty:
                parts.extend([p for p in g.geoms if not p.is_empty])

    if not parts:
        return None

    oriented_parts = [orient(p, sign=1.0) for p in parts if not p.is_empty]
    return MultiPolygon(oriented_parts) if oriented_parts else None


def round_coordinates(coords: Any, precision: int = 6) -> Any:
    """Redondea coordenadas GeoJSON a `precision` decimales (~0.1 m en precision=6)."""
    if isinstance(coords, (float, int)):
        return round(float(coords), precision)
    return [round_coordinates(c, precision) for c in coords]


def validate_colombia_bbox(geom: MultiPolygon, bbox: tuple[float, float, float, float] = COLOMBIA_BBOX) -> bool:
    """Verifica que la geometría en EPSG:4326 caiga dentro de la caja envolvente de Colombia."""
    minx, miny, maxx, maxy = geom.bounds
    bx0, by0, bx1, by1 = bbox
    return bx0 <= minx and maxx <= bx1 and by0 <= miny and maxy <= by1


def prepare_municipalities_gdf(
    gdf: gpd.GeoDataFrame,
    area_crs: str = "EPSG:9377",
    storage_crs: str = "EPSG:4326",
) -> tuple[gpd.GeoDataFrame, int]:
    """Valida, repara geometrías, calcula área en km² y reproyecta al CRS de almacenamiento."""
    if gdf.crs is None:
        raise ValueError("El GeoDataFrame de entrada no tiene CRS definido.")

    work = gdf.copy()
    work["divipola"] = work["divipola"].apply(normalize_divipola)
    work["department_code"] = work["divipola"].str[:2]

    repaired_geoms = []
    rejected_count = 0
    for geom in work.geometry:
        fixed = repair_and_to_multipolygon(geom)
        if fixed is None or not fixed.is_valid:
            repaired_geoms.append(None)
            rejected_count += 1
        else:
            repaired_geoms.append(fixed)

    work["geometry"] = repaired_geoms
    work = work.dropna(subset=["geometry"]).copy()

    area_gdf = work.to_crs(area_crs)
    work["area_km2"] = (area_gdf.geometry.area / 1_000_000.0).round(4)

    storage_gdf = work.to_crs(storage_crs)
    storage_gdf["geometry"] = storage_gdf["geometry"].apply(repair_and_to_multipolygon)

    in_bounds = storage_gdf["geometry"].apply(validate_colombia_bbox)
    rejected_count += int((~in_bounds).sum())
    storage_gdf = storage_gdf[in_bounds].copy()

    return storage_gdf, rejected_count


def build_municipality_document(
    row: Any,
    mgn_version: str = "MGN2025",
    coord_precision: int = 6,
) -> dict[str, Any]:
    """Construye un documento compatible con la colección `municipalities`."""
    geojson_geom = mapping(row.geometry)
    geojson_geom = {
        "type": geojson_geom["type"],
        "coordinates": round_coordinates(geojson_geom["coordinates"], coord_precision),
    }

    divipola = normalize_divipola(row["divipola"])
    doc = {
        "_id": divipola,
        "name": str(row["name"]).strip(),
        "department_code": divipola[:2],
        "department_name": str(row["department_name"]).strip(),
        "pdet_subregion": str(row["pdet_subregion"]).strip(),
        "area_km2": float(row["area_km2"]),
        "geometry": geojson_geom,
        "mgn_version": mgn_version,
    }

    approx_bytes = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    if approx_bytes >= 15_500_000:
        raise ValueError(
            f"El documento del municipio {divipola} ({approx_bytes} bytes) "
            "se acerca al límite BSON de 16 MB de MongoDB."
        )
    return doc


def build_ingestion_log_document(
    dataset: str,
    file_name: str,
    rows_read: int,
    rows_inserted: int,
    rows_rejected: int,
    checksum: str,
) -> dict[str, Any]:
    """Construye el registro de bitácora para la colección `ingestion_log`."""
    return {
        "dataset": dataset,
        "file": file_name,
        "rows_read": int(rows_read),
        "rows_inserted": int(rows_inserted),
        "rows_rejected": int(rows_rejected),
        "checksum": checksum,
        "loaded_at": datetime.now(timezone.utc),
    }
