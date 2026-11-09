"""Funciones compartidas: validación de municipios PDET, construcción de documentos y lectura de planes explain().

No depende de MongoDB (solo shapely/pyproj/yaml), así que se puede probar sin base de datos.
"""
import hashlib
import re
from pathlib import Path

import numpy as np
import shapely
import yaml
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity, make_valid

REPO_ROOT = Path(__file__).resolve().parents[1]   # las rutas de config son relativas a la raíz del repo
CODE_RE = re.compile(r"^\d{5}$")

# Nombres alternativos de propiedades (el ETL puede conservar los nombres originales del MGN)
ALIASES = {
    "code": ["municipality_code", "_id", "MPIO_CDPMP", "mpio_cdpmp", "DIVIPOLA", "divipola"],
    "name": ["name", "MPIO_CNMBR", "mpio_cnmbr", "municipio"],
    "department_code": ["department_code", "DPTO_CCDGO", "dpto_ccdgo"],
    "department_name": ["department_name", "DPTO_CNMBR", "dpto_cnmbr", "departamento"],
    "pdet_subregion": ["pdet_subregion", "subregion", "subregion_pdet"],
    "area_km2": ["area_km2"],
}

_TO_AREA_CRS = Transformer.from_crs("EPSG:4326", "EPSG:9377", always_xy=True)


def load_params(base=REPO_ROOT):
    """Combina config/params.yaml (Mongo, CRS) con config/spatial.yaml (esta entrega)."""
    base = Path(base)
    params = yaml.safe_load((base / "config/params.yaml").read_text(encoding="utf-8")) or {}
    spatial = yaml.safe_load((base / "config/spatial.yaml").read_text(encoding="utf-8")) or {}
    params.update(spatial)
    return params


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _pick(props, key):
    for name in ALIASES[key]:
        v = props.get(name)
        if v is not None and str(v).strip() != "":
            return v
    return None


def normalize_geometry(geom_dict, bbox, repair=False):
    """Devuelve (MultiPolygon GeoJSON listo para 2dsphere, aviso/None). Lanza ValueError si no es utilizable."""
    if not geom_dict:
        raise ValueError("geometría vacía")
    g = shape(geom_dict)
    if g.is_empty:
        raise ValueError("geometría vacía")
    note = None
    if not g.is_valid:
        if not repair:
            raise ValueError("geometría inválida: " + explain_validity(g))
        g = make_valid(g)
        polys = [p for p in getattr(g, "geoms", [g]) if isinstance(p, (Polygon, MultiPolygon))]
        parts = []
        for p in polys:
            parts.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
        if not parts:
            raise ValueError("no quedó geometría poligonal tras repararla")
        g = MultiPolygon(parts)
        note = "reparada con make_valid"
    if g.geom_type == "Polygon":
        g = MultiPolygon([g])
    if g.geom_type != "MultiPolygon":
        raise ValueError(f"tipo de geometría no soportado: {g.geom_type}")
    minx, miny, maxx, maxy = g.bounds
    bx0, by0, bx1, by1 = bbox
    if not (bx0 <= minx and maxx <= bx1 and by0 <= miny and maxy <= by1):
        raise ValueError(
            f"fuera de la caja de Colombia {bbox}: bounds={tuple(round(v, 4) for v in g.bounds)} "
            "(¿coordenadas invertidas o CRS distinto de EPSG:4326?)")
    # Regla de la mano derecha: anillo exterior antihorario, huecos horarios
    g = MultiPolygon([orient(p, sign=1.0) for p in g.geoms])
    return mapping(g), note


def area_km2(geojson_geom):
    g = shapely.transform(shape(geojson_geom),
                          lambda a: np.column_stack(_TO_AREA_CRS.transform(a[:, 0], a[:, 1])))
    return g.area / 1e6


def build_document(feature, cfg, repair=False):
    """Convierte un Feature en documento de la colección municipalities (esquema de la Entrega 1)."""
    props = feature.get("properties") or {}
    code = _pick(props, "code")
    if code is None:
        raise ValueError("falta el código DIVIPOLA")
    code = str(code).strip()
    if code.isdigit() and len(code) < 5:
        code = code.zfill(5)          # 5045 -> 05045 (Excel/pandas pierden el cero inicial)
    if not CODE_RE.match(code):
        raise ValueError(f"código DIVIPOLA inválido: {code!r}")
    name = _pick(props, "name")
    sub = _pick(props, "pdet_subregion")
    if name is None:
        raise ValueError("falta el nombre del municipio")
    if sub is None:
        raise ValueError("falta la subregión PDET")
    geom, note = normalize_geometry(feature.get("geometry"), cfg["validation"]["bbox"], repair)
    dep_code = _pick(props, "department_code")
    dep_code = str(dep_code).zfill(2) if dep_code is not None else code[:2]
    area = _pick(props, "area_km2")
    doc = {
        "_id": code,
        "name": str(name).strip(),
        "department_code": dep_code,
        "department_name": (str(_pick(props, "department_name")).strip()
                            if _pick(props, "department_name") is not None else None),
        "pdet_subregion": str(sub).strip(),
        "area_km2": float(area) if area is not None else round(area_km2(geom), 3),
        "geometry": geom,
        "mgn_version": cfg["input"]["mgn_version"],
    }
    return doc, note


# ---------------------------------------------------------------- lectura de planes explain()
def _walk(node, stages, indexes):
    if isinstance(node, dict):
        if isinstance(node.get("stage"), str):
            stages.append(node["stage"])
        if isinstance(node.get("indexName"), str):
            indexes.append(node["indexName"])
        for v in node.values():
            _walk(v, stages, indexes)
    elif isinstance(node, list):
        for v in node:
            _walk(v, stages, indexes)


def summarize_explain(res):
    """Resume la salida de explain('executionStats') en los datos que se citan como evidencia."""
    plan = res.get("queryPlanner", {}).get("winningPlan", {})
    stages, indexes = [], []
    _walk(plan, stages, indexes)
    stats = res.get("executionStats", {})
    uses_index = any(s in ("IXSCAN", "GEO_NEAR_2DSPHERE") for s in stages)
    return {
        "stages": stages,
        "index_used": indexes[0] if indexes else None,
        "uses_index": uses_index,
        "collscan": "COLLSCAN" in stages,
        "keys_examined": stats.get("totalKeysExamined"),
        "docs_examined": stats.get("totalDocsExamined"),
        "n_returned": stats.get("nReturned"),
        "millis": stats.get("executionTimeMillis"),
    }
