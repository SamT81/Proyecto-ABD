"""Funciones de apoyo para descargar y verificar el MGN del DANE y filtrar los municipios PDET.

Se usan desde los scripts 00a, 00b y 00c. Las funciones de validación no dependen de la red ni de
MongoDB, para poder probarlas con datos pequeños (ver tests/test_mgn_acquisition.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_RE = re.compile(r"^\d{5}$")

OK, AVISO, FALLA = "OK", "AVISO", "FALLA"


def load_config(path=None):
    path = Path(path) if path else REPO_ROOT / "config" / "acquisition.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def repo_path(rel):
    """Las rutas del YAML son relativas a la raíz del repo, sin importar desde dónde se ejecute."""
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_code(value):
    """Código DIVIPOLA municipal a 5 dígitos. Excel guarda 5490 en vez de 05490."""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if not s.isdigit() or len(s) > 5:
        raise ValueError(f"código DIVIPOLA inválido: {value!r}")
    return s.zfill(5)


def normalize_name(value):
    """Nombre comparable: sin tildes, mayúsculas, sin signos y con espacios simples."""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper()
    return re.sub(r"\s+", " ", s).strip()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# Registro de controles de calidad
# --------------------------------------------------------------------------------------------

class QCReport:
    """Acumula los controles en orden. Cada control queda como OK, AVISO o FALLA con su detalle."""

    def __init__(self):
        self.checks = []

    def add(self, check_id, descripcion, resultado, detalle=""):
        self.checks.append({"id": check_id, "control": descripcion,
                            "resultado": resultado, "detalle": detalle})
        print(f"[{resultado:5}] {check_id} {descripcion}" + (f": {detalle}" if detalle else ""))
        return resultado

    def expect(self, check_id, descripcion, condicion, detalle="", nivel=FALLA):
        return self.add(check_id, descripcion, OK if condicion else nivel, detalle)

    @property
    def failed(self):
        return [c for c in self.checks if c["resultado"] == FALLA]

    def summary(self):
        out = {OK: 0, AVISO: 0, FALLA: 0}
        for c in self.checks:
            out[c["resultado"]] += 1
        return out


# --------------------------------------------------------------------------------------------
# Catálogo PDET
# --------------------------------------------------------------------------------------------

CATALOG_COLUMNS = ["divipola", "municipio", "dpto_ccdgo", "departamento",
                   "pdet_subregion_id", "pdet_subregion"]


def catalog_from_rows(rows):
    """Convierte filas del Excel de la ART (dicts) al catálogo con códigos normalizados.

    Columnas esperadas: Subregión PDET, Código DANE Departamento, Departamento,
    Código DANE Municipio, Municipio. El id de subregión se asigna en orden alfabético, igual que
    en la hoja "Hoja1" del archivo original.
    """
    import pandas as pd

    df = pd.DataFrame(rows)
    cols = {normalize_name(c): c for c in df.columns}
    needed = {
        "pdet_subregion": "SUBREGION PDET",
        "dpto_ccdgo": "CODIGO DANE DEPARTAMENTO",
        "departamento": "DEPARTAMENTO",
        "divipola": "CODIGO DANE MUNICIPIO",
        "municipio": "MUNICIPIO",
    }
    missing = [v for v in needed.values() if v not in cols]
    if missing:
        raise KeyError(f"faltan columnas en el listado PDET: {missing}. Disponibles: {list(df.columns)}")

    out = pd.DataFrame({k: df[cols[v]] for k, v in needed.items()})
    out = out.dropna(how="all")
    out["divipola"] = out["divipola"].apply(normalize_code)
    out["dpto_ccdgo"] = out["dpto_ccdgo"].apply(lambda v: normalize_code(v)[-2:])
    for c in ("pdet_subregion", "departamento", "municipio"):
        out[c] = out[c].astype(str).str.strip()
    subregions = sorted(out["pdet_subregion"].unique(), key=normalize_name)
    ids = {s: i + 1 for i, s in enumerate(subregions)}
    out["pdet_subregion_id"] = out["pdet_subregion"].map(ids)
    return out[CATALOG_COLUMNS].sort_values("divipola").reset_index(drop=True)


def check_catalog(cat, qc, expected_mpios=170, expected_subregions=16):
    """Controles sobre el listado PDET antes de cruzarlo con el MGN."""
    n = len(cat)
    qc.expect("PDET-01", "Municipios en el listado PDET", n == expected_mpios,
              f"{n} (esperados {expected_mpios})")
    dups = sorted(cat.loc[cat["divipola"].duplicated(keep=False), "divipola"].unique())
    qc.expect("PDET-02", "Códigos DIVIPOLA únicos en el listado", not dups,
              f"duplicados: {dups}" if dups else "sin duplicados")
    bad = [c for c in cat["divipola"] if not CODE_RE.match(c)]
    qc.expect("PDET-03", "Códigos con formato de 5 dígitos", not bad, f"inválidos: {bad}" if bad else "")
    ns = cat["pdet_subregion"].nunique()
    qc.expect("PDET-04", "Subregiones PDET", ns == expected_subregions, f"{ns} (esperadas {expected_subregions})")
    incoherent = cat.loc[cat["divipola"].str[:2] != cat["dpto_ccdgo"], "divipola"].tolist()
    qc.expect("PDET-05", "Prefijo del código municipal = código de departamento", not incoherent,
              f"incoherentes: {incoherent}" if incoherent else "")
    nulls = int(cat[CATALOG_COLUMNS].isna().sum().sum())
    qc.expect("PDET-06", "Campos sin valores nulos", nulls == 0, f"{nulls} nulos")


# --------------------------------------------------------------------------------------------
# Capa municipal del MGN
# --------------------------------------------------------------------------------------------

MGN_REQUIRED = ["dpto_ccdgo", "mpio_ccdgo", "mpio_cdpmp", "dpto_cnmbr", "mpio_cnmbr",
                "mpio_tipo", "mpio_narea"]


def lower_columns(gdf):
    """El DANE ha publicado los campos en mayúsculas (MGN2023) y en minúsculas (MGN2025)."""
    return gdf.rename(columns={c: c.lower() for c in gdf.columns if c != gdf.geometry.name})


def check_mgn_layer(gdf, qc, expected_crs="EPSG:4326", expected_mpios=None, bbox=None):
    """Controles sobre la capa nacional completa, antes de filtrar."""
    missing = [c for c in MGN_REQUIRED if c not in gdf.columns]
    qc.expect("MGN-01", "Campos requeridos presentes en la capa", not missing,
              f"faltan: {missing}" if missing else ", ".join(MGN_REQUIRED))
    if missing:
        return

    epsg = gdf.crs.to_epsg() if gdf.crs else None
    qc.expect("MGN-02", "Sistema de referencia de la capa", gdf.crs is not None and f"EPSG:{epsg}" == expected_crs,
              f"EPSG:{epsg} (esperado {expected_crs})")
    if expected_mpios:
        qc.expect("MGN-03", "Unidades en la capa municipal", len(gdf) == expected_mpios,
                  f"{len(gdf)} (esperadas {expected_mpios})", nivel=AVISO)
    codes = gdf["mpio_cdpmp"].astype(str)
    dups = int(codes.duplicated().sum())
    qc.expect("MGN-04", "mpio_cdpmp único", dups == 0, f"{dups} duplicados")
    bad = int((~codes.str.match(CODE_RE)).sum())
    qc.expect("MGN-05", "mpio_cdpmp con 5 dígitos", bad == 0, f"{bad} inválidos")
    incoherent = int((codes.str[:2] != gdf["dpto_ccdgo"].astype(str)).sum()
                     + (codes.str[2:] != gdf["mpio_ccdgo"].astype(str)).sum())
    qc.expect("MGN-06", "mpio_cdpmp = dpto_ccdgo + mpio_ccdgo", incoherent == 0, f"{incoherent} incoherentes")
    nulls = int(gdf[MGN_REQUIRED].isna().sum().sum()) + int(gdf.geometry.isna().sum())
    qc.expect("MGN-07", "Atributos y geometrías sin nulos", nulls == 0, f"{nulls} nulos")
    if bbox:
        minx, miny, maxx, maxy = gdf.total_bounds
        inside = minx >= bbox[0] and miny >= bbox[1] and maxx <= bbox[2] and maxy <= bbox[3]
        qc.expect("MGN-08", "Extensión dentro de la caja de Colombia", inside,
                  f"[{minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f}]")


def join_catalog(gdf, cat, qc):
    """Filtra la capa a los municipios del catálogo y verifica que el cruce sea completo."""
    mgn_codes = set(gdf["mpio_cdpmp"].astype(str))
    not_found = sorted(set(cat["divipola"]) - mgn_codes)
    qc.expect("JOIN-01", "Códigos PDET encontrados en el MGN", not not_found,
              f"{len(cat) - len(not_found)}/{len(cat)}" + (f"; no encontrados: {not_found}" if not_found else ""))

    sub = gdf.merge(cat, left_on="mpio_cdpmp", right_on="divipola", how="inner")
    sub = sub.drop(columns=["divipola"])

    dept_bad = sub.loc[sub["dpto_ccdgo_x"] != sub["dpto_ccdgo_y"], "mpio_cdpmp"].tolist()
    qc.expect("JOIN-02", "Departamento del listado = departamento del MGN", not dept_bad,
              f"distintos: {dept_bad}" if dept_bad else "")
    sub = sub.drop(columns=["dpto_ccdgo_y"]).rename(columns={"dpto_ccdgo_x": "dpto_ccdgo"})

    diff = sub[sub["mpio_cnmbr"].map(normalize_name) != sub["municipio"].map(normalize_name)]
    detail = "; ".join(f"{r.mpio_cdpmp}: MGN '{r.mpio_cnmbr}' / ART '{r.municipio}'" for r in diff.itertuples())
    # Un nombre distinto no invalida el cruce (la llave es el código), pero se documenta.
    qc.expect("JOIN-03", "Nombre del municipio coincide (sin tildes)", diff.empty,
              detail or f"{len(sub)} coincidencias", nivel=AVISO)
    return sub


def check_pdet_layer(sub, qc, cfg):
    """Controles sobre los 170 polígonos filtrados: geometría, áreas, solapes y tamaño del documento."""
    import geopandas as gpd
    import shapely
    from shapely.validation import explain_validity

    q = cfg["qc"]
    exp = cfg["pdet"]["expected_municipalities"]
    n = len(sub)
    qc.expect("GEO-01", "Municipios PDET en la capa filtrada", n == exp, f"{n} (esperados {exp})")
    qc.expect("GEO-02", "Un polígono por código", sub["mpio_cdpmp"].is_unique, "")

    types = sub.geom_type.value_counts().to_dict()
    qc.expect("GEO-03", "Tipos de geometría Polygon/MultiPolygon",
              set(types) <= {"Polygon", "MultiPolygon"}, json.dumps(types))
    empty = int(sub.is_empty.sum())
    qc.expect("GEO-04", "Geometrías no vacías", empty == 0, f"{empty} vacías")
    invalid = sub[~sub.is_valid]
    detail = "; ".join(f"{r.mpio_cdpmp}: {explain_validity(r.geometry)}" for r in invalid.itertuples())
    # El ETL (01_load_municipalities.py) repara con make_valid, por eso aquí es aviso.
    qc.expect("GEO-05", "Geometrías válidas (OGC)", invalid.empty,
              detail or f"{n} válidas", nivel=AVISO)

    sub = sub.copy()
    sub["area_km2_calc"] = sub.to_crs(q["area_crs"]).area / 1e6
    rel = (sub["area_km2_calc"] - sub["mpio_narea"]).abs() / sub["mpio_narea"] * 100
    worst = sub.loc[rel.idxmax()]
    qc.expect("GEO-06", f"Área en {q['area_crs']} vs mpio_narea del DANE",
              rel.max() <= q["max_area_diff_pct"],
              f"diferencia máx. {rel.max():.3f}% ({worst['mpio_cdpmp']} {worst['mpio_cnmbr']}), media {rel.mean():.3f}%")
    small = sub.loc[sub["area_km2_calc"] <= 0, "mpio_cdpmp"].tolist()
    qc.expect("GEO-07", "Áreas positivas", not small, f"{small}" if small else
              f"total PDET {sub['area_km2_calc'].sum():,.0f} km²")

    # Solapes entre vecinos: se proyecta para medir en km² y se descartan los contactos de borde.
    proj = sub[["mpio_cdpmp", "geometry"]].to_crs(q["area_crs"])
    pairs = gpd.sjoin(proj, proj, predicate="intersects")
    pairs = pairs[pairs["mpio_cdpmp_left"] < pairs["mpio_cdpmp_right"]]
    geoms = proj.set_index("mpio_cdpmp").geometry
    overlaps = []
    for a, b in zip(pairs["mpio_cdpmp_left"], pairs["mpio_cdpmp_right"]):
        area = shapely.intersection(shapely.make_valid(geoms[a]), shapely.make_valid(geoms[b])).area / 1e6
        if area > q["max_overlap_km2"]:
            overlaps.append(f"{a}-{b}: {area:.3f} km²")
    qc.expect("GEO-08", "Sin solapes entre municipios PDET vecinos", not overlaps,
              "; ".join(overlaps) if overlaps else f"{len(pairs)} pares vecinos revisados", nivel=AVISO)

    # Tamaño estimado del documento GeoJSON por municipio (límite BSON 16 MB).
    vertices = shapely.get_num_coordinates(sub.geometry.values)
    sizes_mb = [len(json.dumps(shapely.geometry.mapping(g))) / 1e6 for g in sub.geometry]
    i = max(range(n), key=lambda k: sizes_mb[k])
    qc.expect("GEO-09", "Tamaño de la geometría por documento", max(sizes_mb) < q["max_doc_mb"],
              f"máx. {sizes_mb[i]:.2f} MB ({sub.iloc[i]['mpio_cdpmp']}, {int(vertices[i]):,} vértices); "
              f"vértices totales {int(vertices.sum()):,}")
    tipos = sub["mpio_tipo"].value_counts().to_dict()
    qc.add("GEO-10", "Tipo de entidad territorial (mpio_tipo)", OK, json.dumps(tipos, ensure_ascii=False))
    return sub, {"vertices": vertices, "sizes_mb": sizes_mb}
