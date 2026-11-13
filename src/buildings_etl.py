"""Transformación de huellas de edificios: lectura por bloques, limpieza, asignación de municipio y área.

Cada partición descargada (quadkey de Microsoft o celda S2 de Google) se procesa por bloques y se escribe
como GeoParquet en data/processed/buildings/<fuente>/<partición>/part-NNNNN.parquet, con los campos de la
colección correspondiente (buildings_microsoft o buildings_google, ver Entrega 1). La carga a MongoDB lee
esos archivos. El módulo no usa MongoDB ni red, así que se prueba con datos sintéticos.
"""
from __future__ import annotations

import gzip
import itertools
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

GOOGLE_COLUMNS = ["latitude", "longitude", "area_in_meters", "confidence", "geometry", "full_plus_code"]
OUTPUT_COLUMNS = {
    "microsoft": ["geometry", "area_m2", "municipality_code", "source_file", "is_valid_geom"],
    "google": ["geometry", "area_m2", "confidence", "full_plus_code", "municipality_code", "source_file",
               "is_valid_geom"],
}
POLYGON = shapely.GeometryType.POLYGON


# --------------------------------------------------------------------------------------------
# Municipios PDET
# --------------------------------------------------------------------------------------------

class PdetIndex:
    """Polígonos PDET preparados para asignar puntos a municipios de forma vectorizada.

    El STRtree solo descarta por caja envolvente; la prueba exacta se hace con intersects_xy sobre el
    polígono preparado, que es mucho más rápido que evaluar cada punto contra polígonos de miles de vértices.
    """

    def __init__(self, codes, geometries, prefilter_deg=0.0):
        self.codes = np.asarray(codes, dtype=object)
        self.geoms = np.asarray(geometries, dtype=object)
        shapely.prepare(self.geoms)
        self.tree = shapely.STRtree(self.geoms)
        self.wide = None
        if prefilter_deg:
            self.wide = shapely.buffer(self.geoms, prefilter_deg, quad_segs=2)
            shapely.prepare(self.wide)
            self.wide_tree = shapely.STRtree(self.wide)

    @classmethod
    def from_gdf(cls, gdf, code_col="mpio_cdpmp", prefilter_deg=0.0):
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            raise ValueError("los municipios PDET deben estar en EPSG:4326")
        return cls(gdf[code_col].astype(str).values, gdf.geometry.values, prefilter_deg)

    def _match(self, tree, geoms, x, y):
        out = np.full(len(x), -1, dtype=np.int64)
        if len(x) == 0:
            return out
        pts = shapely.points(x, y)
        i_pt, i_poly = tree.query(pts)
        if len(i_pt) == 0:
            return out
        order = np.lexsort((i_pt, i_poly))
        i_pt, i_poly = i_pt[order], i_poly[order]
        cuts = np.flatnonzero(np.diff(i_poly)) + 1
        for pts_idx, polys in zip(np.split(i_pt, cuts), np.split(i_poly, cuts)):
            pending = pts_idx[out[pts_idx] < 0]
            if len(pending):
                hit = shapely.intersects_xy(geoms[polys[0]], x[pending], y[pending])
                out[pending[hit]] = polys[0]
        return out

    def assign(self, x, y):
        """Índice del municipio que contiene cada punto (-1 si ninguno). En un borde compartido gana el primero."""
        return self._match(self.tree, self.geoms, np.asarray(x, float), np.asarray(y, float))

    def near(self, x, y):
        """Máscara de puntos dentro del margen de prefiltro (o dentro de PDET si no hay margen)."""
        if self.wide is None:
            return self.assign(x, y) >= 0
        return self._match(self.wide_tree, self.wide, np.asarray(x, float), np.asarray(y, float)) >= 0


# --------------------------------------------------------------------------------------------
# Geometría
# --------------------------------------------------------------------------------------------

def _largest_polygon(geom):
    """De una colección o multipolígono deja el polígono de mayor área (None si no hay ninguno)."""
    if geom is None or geom.is_empty:
        return None
    if shapely.get_type_id(geom) == POLYGON:
        return geom
    polys = [g for g in shapely.get_parts(geom) if shapely.get_type_id(g) == POLYGON and not g.is_empty]
    if not polys:
        nested = [p for g in shapely.get_parts(geom) for p in shapely.get_parts(g)
                  if shapely.get_type_id(p) == POLYGON and not p.is_empty]
        polys = nested
    return max(polys, key=lambda p: p.area) if polys else None


def _to_polygons(out, ok):
    """Reduce a Polygon las geometrías marcadas en `ok`. Devuelve la máscara de las que eran multiparte."""
    multi = np.zeros(len(out), dtype=bool)
    types = np.full(len(out), -1)
    types[ok] = shapely.get_type_id(out[ok])
    for i in np.flatnonzero(ok & (types != POLYGON)):
        if out[i] is not None and not out[i].is_empty:
            multi[i] = len(shapely.get_parts(out[i])) > 1
        out[i] = _largest_polygon(out[i])
    return multi


def clean_geometries(geoms):
    """Repara (make_valid) y reduce cada geometría a un Polygon válido.

    Devuelve (geometrías, era_válida, motivo, multiparte): motivo es "" si la geometría se conserva o la causa
    del descarte. Las multipartes se reducen al polígono más grande y se cuentan aparte.
    """
    geoms = np.asarray(geoms, dtype=object)
    n = len(geoms)
    reason = np.full(n, "", dtype=object)
    missing = shapely.is_missing(geoms) | shapely.is_empty(geoms)
    reason[missing] = "vacía o ilegible"

    valid = np.zeros(n, dtype=bool)
    ok = ~missing
    valid[ok] = shapely.is_valid(geoms[ok])
    out = geoms.copy()
    bad = ok & ~valid
    if bad.any():
        out[bad] = shapely.make_valid(geoms[bad])
    multi = _to_polygons(out, ok)

    gone = ok & (shapely.is_missing(out) | shapely.is_empty(out))
    reason[gone] = "sin polígono tras reparar"
    keep = ok & ~gone
    still_bad = keep.copy()
    still_bad[keep] = ~shapely.is_valid(out[keep])
    reason[still_bad] = "inválida tras reparar"
    out[reason != ""] = None
    return out, valid, reason, multi


def round_geometries(geoms, precision=6):
    """Redondea a `precision` decimales sin romper la validez y orienta los anillos (exterior antihorario).

    set_precision ajusta la geometría a la grilla conservándola válida; un edificio muy pequeño puede colapsar
    y en ese caso se devuelve None. La orientación es la de la regla de la mano derecha de GeoJSON.
    """
    geoms = np.asarray(geoms, dtype=object)
    out = shapely.set_precision(geoms, 10.0 ** -precision)
    ok = ~(shapely.is_missing(out) | shapely.is_empty(out))
    _to_polygons(out, ok)
    ok = ~(shapely.is_missing(out) | shapely.is_empty(out))
    ok[ok] = shapely.is_valid(out[ok])
    out[ok] = shapely.orient_polygons(out[ok], exterior_cw=False)
    out[~ok] = None
    return out, ok


def make_area_fn(area_crs="EPSG:9377"):
    tr = Transformer.from_crs("EPSG:4326", area_crs, always_xy=True)

    def project(coords):
        x, y = tr.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    def area_m2(geoms):
        geoms = np.asarray(geoms, dtype=object)
        if len(geoms) == 0:
            return np.array([], dtype=float)
        return shapely.area(shapely.transform(geoms, project))

    return area_m2


# --------------------------------------------------------------------------------------------
# Lectura por bloques
# --------------------------------------------------------------------------------------------

def read_microsoft(path, chunk_rows):
    """Bloques de geometrías desde el GeoJSON por líneas de Microsoft."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        while True:
            lines = [ln for ln in itertools.islice(f, chunk_rows) if ln.strip()]
            if not lines:
                return
            geoms = shapely.from_geojson(lines, on_invalid="ignore")
            yield len(lines), pd.DataFrame({"geometry": geoms})


def read_google(path, chunk_rows, keep=None):
    """Bloques del CSV de Google. Si se da `keep(lon, lat)`, el WKT solo se interpreta en las filas que pasan."""
    reader = pd.read_csv(path, chunksize=chunk_rows, usecols=GOOGLE_COLUMNS,
                         dtype={"full_plus_code": str, "geometry": str})
    for df in reader:
        n = len(df)
        if keep is not None:
            df = df[keep(df["longitude"].to_numpy(), df["latitude"].to_numpy())]
        df = df.reset_index(drop=True)
        df["geometry"] = shapely.from_wkt(df["geometry"].to_numpy(), on_invalid="ignore")
        yield n, df


# --------------------------------------------------------------------------------------------
# Proceso de una partición
# --------------------------------------------------------------------------------------------

def transform_chunk(df, source, source_file, pdet, area_fn, precision=6):
    """Aplica limpieza, asignación y área a un bloque. Devuelve (salida, estadísticas, muestra de áreas)."""
    stats = {"leidos_bloque": len(df)}
    geoms, valid, reason, multi = clean_geometries(df["geometry"].to_numpy())

    # Primero se asigna el municipio: los rechazos y reparaciones se cuentan solo dentro de PDET.
    keep = reason == ""
    pts = shapely.point_on_surface(geoms[keep])
    idx_keep = pdet.assign(shapely.get_x(pts), shapely.get_y(pts))
    idx = np.full(len(df), -1, dtype=np.int64)
    idx[keep] = idx_keep
    if not keep.all():
        # Una geometría irrecuperable no tiene punto representativo; se ubica por el centro de su caja.
        bad = np.flatnonzero(~keep)
        raw = df["geometry"].to_numpy()[bad]
        has = ~(shapely.is_missing(raw) | shapely.is_empty(raw))
        if has.any():
            c = shapely.centroid(shapely.envelope(raw[has]))
            idx[bad[has]] = pdet.assign(shapely.get_x(c), shapely.get_y(c))
    inside = idx >= 0
    stats["fuera_pdet"] = int((~inside).sum())

    # El área se mide sobre la geometría reparada sin redondear; el redondeo es solo para almacenarla.
    rows = np.flatnonzero(keep & inside)
    calc = area_fn(geoms[rows])
    g, ok = round_geometries(geoms[rows], precision)
    reason_in = reason[inside].copy()
    for motivo in ("vacía o ilegible", "sin polígono tras reparar", "inválida tras reparar"):
        stats[f"rechazados:{motivo}"] = int((reason_in == motivo).sum())
    stats["rechazados:colapsó al redondear"] = int((~ok).sum())
    stats["reparados"] = int((~valid[rows] & ok).sum())
    stats["multiparte_reducidos"] = int((multi[rows] & ok).sum())

    rows, g, calc = rows[ok], g[ok], calc[ok]
    out = pd.DataFrame({"geometry": g})
    sample = None
    if source == "google":
        orig = df["area_in_meters"].to_numpy(float)[rows]
        out["area_m2"] = orig
        out["confidence"] = df["confidence"].to_numpy(float)[rows]
        out["full_plus_code"] = df["full_plus_code"].to_numpy(object)[rows]
        with np.errstate(divide="ignore", invalid="ignore"):
            sample = (calc - orig) / orig
    else:
        out["area_m2"] = np.round(calc, 3)
    out["municipality_code"] = pdet.codes[idx[rows]]
    out["source_file"] = source_file
    out["is_valid_geom"] = valid[rows]
    stats["escritos"] = len(out)
    return out[OUTPUT_COLUMNS[source]], stats, sample


def iter_documents(partition_dir, batch_size=None):
    """Lee la salida de una partición por row groups y entrega listas de documentos para insert_many.

    Cada documento tiene los campos de la colección (geometry como GeoJSON). No carga el archivo completo en
    memoria: cada lote es un row group (o `batch_size` filas si se indica).
    """
    import pyarrow.parquet as pq

    for f in sorted(Path(partition_dir).glob("part-*.parquet")):
        pf = pq.ParquetFile(f)
        batches = pf.iter_batches(batch_size=batch_size) if batch_size else \
            (pf.read_row_group(i) for i in range(pf.num_row_groups))
        for batch in batches:
            cols = batch.to_pydict()
            geoms = shapely.from_wkb(cols.pop("geometry"))
            names = list(cols)
            docs = []
            for i, g in enumerate(geoms):
                d = {"geometry": shapely.geometry.mapping(g)}
                for k in names:
                    d[k] = cols[k][i]
                docs.append(d)
            yield docs


def _write_part(df, path, row_group_size):
    import geopandas as gpd

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf.to_parquet(path, index=False, compression="zstd", row_group_size=row_group_size,
                   schema_version="1.0.0")


def _area_summary(values):
    v = values[np.isfinite(values)] if len(values) else values
    if len(v) == 0:
        return None
    q = np.percentile(np.abs(v), [50, 95, 99])
    return {"n": int(len(v)), "media_rel": float(v.mean()), "mediana_abs_rel": float(q[0]),
            "p95_abs_rel": float(q[1]), "p99_abs_rel": float(q[2])}


def process_partition(task):
    """Procesa una partición completa. Se ejecuta en un proceso aparte (ver 01b_etl_buildings.py).

    Escribe primero en <partición>.tmp y renombra al terminar, de modo que una corrida cortada no deja
    archivos a medias que la carga pueda leer.
    """
    import geopandas as gpd

    t0 = time.time()
    source, part_id, raw = task["source"], task["partition_id"], Path(task["raw_file"])
    out_dir = Path(task["out_dir"])
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    pdet_gdf = gpd.read_file(task["pdet_gpkg"], layer=task["pdet_layer"])
    if task.get("municipios"):
        pdet_gdf = pdet_gdf[pdet_gdf["mpio_cdpmp"].isin(task["municipios"])]
    pdet = PdetIndex.from_gdf(pdet_gdf, prefilter_deg=task["prefilter_deg"] if source == "google" else 0.0)
    area_fn = make_area_fn(task["area_crs"])

    totals = {"leidos": 0, "prefiltrados_fuera": 0, "fuera_pdet": 0, "reparados": 0,
              "multiparte_reducidos": 0, "escritos": 0}
    per_mpio, area_rel, hashes = {}, [], []
    n_parts = 0
    if source == "google":
        chunks = read_google(raw, task["chunk_rows"], keep=pdet.near)
    else:
        chunks = read_microsoft(raw, task["chunk_rows"])
    for n_read, df in chunks:
        totals["leidos"] += n_read
        totals["prefiltrados_fuera"] += n_read - len(df)
        if df.empty:
            continue
        out, stats, sample = transform_chunk(df, source, raw.name, pdet, area_fn, task["precision"])
        for k, v in stats.items():
            if k != "leidos_bloque":
                totals[k] = totals.get(k, 0) + v
        if sample is not None and len(sample):
            area_rel.append(sample)
        if out.empty:
            continue
        for code, cnt in out["municipality_code"].value_counts().items():
            per_mpio[code] = per_mpio.get(code, 0) + int(cnt)
        wkb = shapely.to_wkb(out["geometry"].to_numpy())
        hashes.append(pd.util.hash_array(wkb.astype(object)).astype(np.uint64))
        _write_part(out, tmp / f"part-{n_parts:05d}.parquet", task["row_group_size"])
        n_parts += 1

    totals["fuera_pdet"] = totals.get("fuera_pdet", 0) + totals.pop("prefiltrados_fuera")
    rel = np.concatenate(area_rel) if area_rel else np.array([])
    summary = {
        "source": source,
        "partition_id": part_id,
        "archivo": raw.name,
        "sha256_entrada": task["sha256"],
        "archivos_salida": n_parts,
        "segundos": round(time.time() - t0, 1),
        **totals,
        "por_municipio": dict(sorted(per_mpio.items())),
        "area_google_vs_9377": _area_summary(rel) if source == "google" else None,
    }
    (tmp / "_SUCCESS.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.rename(out_dir)
    summary["hashes"] = np.concatenate(hashes) if hashes else np.array([], dtype=np.uint64)
    return summary
