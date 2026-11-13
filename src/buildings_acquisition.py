"""Funciones de apoyo para seleccionar y descargar las particiones de huellas de edificios.

Microsoft parte su dataset por país y quadkey de nivel 9 (teselas Bing/Web Mercator); Google lo parte en
celdas S2 de nivel 4. En ambos casos se descargan solo las particiones que tocan algún municipio PDET.
Se usan desde src/00d_select_building_partitions.py y src/00e_download_buildings.py. La geometría de las
teselas y las verificaciones no dependen de la red, para poder probarlas (tests/test_buildings_acquisition.py).
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import re
import time
import urllib.request
from pathlib import Path

from mgn_acquisition import AVISO, FALLA, OK, QCReport, load_config, now_iso, repo_path, sha256_file, write_json  # noqa: F401

USER_AGENT = "Proyecto-ABD/1.0 (descarga huellas de edificios)"
SIZE_RE = re.compile(r"^\s*([\d.]+)\s*(B|KB|MB|GB)\s*$", re.IGNORECASE)
SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}

CATALOG_COLUMNS = ["source", "partition_id", "file_name", "url", "size_bytes", "size_exact", "md5_b64",
                   "west", "south", "east", "north", "n_municipios", "municipios"]


def load_buildings_config(path=None):
    return load_config(path or repo_path("config/buildings.yaml"))


# --------------------------------------------------------------------------------------------
# Teselas de Microsoft (quadkeys)
# --------------------------------------------------------------------------------------------

def quadkey_to_tile(quadkey):
    """Quadkey de Bing Maps -> (x, y, z). Cada dígito agrega un nivel: 0 NO, 1 NE, 2 SO, 3 SE."""
    quadkey = str(quadkey).strip()
    if not quadkey or any(c not in "0123" for c in quadkey):
        raise ValueError(f"quadkey inválido: {quadkey!r}")
    x = y = 0
    z = len(quadkey)
    for i, digit in enumerate(quadkey):
        mask = 1 << (z - i - 1)
        d = int(digit)
        if d & 1:
            x |= mask
        if d & 2:
            y |= mask
    return x, y, z


def tile_bounds(x, y, z):
    """Límites lon/lat (oeste, sur, este, norte) de una tesela Web Mercator."""
    n = 2 ** z

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return x / n * 360.0 - 180.0, lat(y + 1), (x + 1) / n * 360.0 - 180.0, lat(y)


def quadkey_bounds(quadkey):
    return tile_bounds(*quadkey_to_tile(quadkey))


def parse_size(text):
    """'615.5KB' -> bytes aproximados. El índice de Microsoft redondea a un decimal."""
    m = SIZE_RE.match(str(text))
    if not m:
        raise ValueError(f"tamaño no reconocido: {text!r}")
    return int(float(m.group(1)) * SIZE_UNITS[m.group(2).upper()])


def size_tolerance(approx_bytes):
    """Margen del tamaño redondeado del índice: una décima de la unidad en que se publicó (KB, MB...)."""
    unit = 1
    while approx_bytes >= unit * 1024 and unit < SIZE_UNITS["GB"]:
        unit *= 1024
    return unit // 10 + 1


# --------------------------------------------------------------------------------------------
# Selección de particiones
# --------------------------------------------------------------------------------------------

def _municipios_por_particion(parts, pdet, buffer_deg):
    """Cruza particiones (GeoDataFrame con partition_id) con los municipios PDET, con un margen en grados."""
    import warnings

    import geopandas as gpd

    zona = pdet[["mpio_cdpmp", "geometry"]].copy()
    if buffer_deg:
        with warnings.catch_warnings():
            # El margen es en grados a propósito (solo amplía la búsqueda); no se usa para medir.
            warnings.simplefilter("ignore", UserWarning)
            zona["geometry"] = zona.geometry.buffer(buffer_deg)
    pairs = gpd.sjoin(parts[["partition_id", "geometry"]], zona, predicate="intersects")
    return pairs.groupby("partition_id")["mpio_cdpmp"].apply(lambda s: sorted(set(s)))


def _catalog(parts, mpios, source):
    import pandas as pd

    parts = parts[parts["partition_id"].isin(mpios.index)].copy()
    b = parts.geometry.bounds
    out = pd.DataFrame({
        "source": source,
        "partition_id": parts["partition_id"].values,
        "file_name": parts["file_name"].values,
        "url": parts["url"].values,
        "size_bytes": parts["size_bytes"].astype("int64").values,
        "size_exact": parts["size_exact"].values,
        "md5_b64": parts["md5_b64"].values,
        "west": b["minx"].round(6).values, "south": b["miny"].round(6).values,
        "east": b["maxx"].round(6).values, "north": b["maxy"].round(6).values,
    })
    lists = out["partition_id"].map(mpios)
    out["n_municipios"] = lists.map(len)
    out["municipios"] = lists.map(";".join)
    return out[CATALOG_COLUMNS].sort_values("partition_id").reset_index(drop=True)


def select_microsoft(index_df, pdet, location="Colombia", buffer_deg=0.0):
    """Filas del índice de Microsoft del país cuyo quadkey toca algún municipio PDET."""
    import geopandas as gpd
    from shapely.geometry import box

    rows = index_df[index_df["Location"] == location].copy()
    if rows.empty:
        raise ValueError(f"el índice de Microsoft no tiene filas para {location!r}")
    rows["QuadKey"] = rows["QuadKey"].astype(str).str.strip()
    rows["partition_id"] = rows["QuadKey"]
    rows["file_name"] = [f"{q}_{Path(u).name}" for q, u in zip(rows["QuadKey"], rows["Url"])]
    rows["url"] = rows["Url"]
    rows["size_bytes"] = rows["Size"].map(parse_size)
    rows["size_exact"] = False      # el índice solo trae el tamaño redondeado
    rows["md5_b64"] = ""            # el MD5 lo entrega el servidor (Content-MD5) al descargar
    geoms = [box(*quadkey_bounds(q)) for q in rows["QuadKey"]]
    parts = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return _catalog(parts, _municipios_por_particion(parts, pdet, buffer_deg), "microsoft")


def select_google(tiles, objects, pdet, prefix, buffer_deg=0.0):
    """Celdas S2 de Google que tocan algún municipio PDET, con tamaño y MD5 del listado del bucket."""
    tiles = tiles.copy()
    tiles["partition_id"] = tiles["tile_id"].astype(str)
    tiles["file_name"] = tiles["partition_id"] + "_buildings.csv.gz"
    meta = {o["name"]: o for o in objects}
    missing = [f for f in tiles["file_name"] if prefix + f not in meta]
    tiles = tiles[~tiles["file_name"].isin(missing)]
    tiles["url"] = [f"https://storage.googleapis.com/open-buildings-data/{prefix}{f}" for f in tiles["file_name"]]
    tiles["size_bytes"] = [int(meta[prefix + f]["size"]) for f in tiles["file_name"]]
    tiles["size_exact"] = True
    tiles["md5_b64"] = [meta[prefix + f].get("md5Hash", "") for f in tiles["file_name"]]
    return _catalog(tiles, _municipios_por_particion(tiles, pdet, buffer_deg), "google"), missing


def list_bucket(api_url, prefix, timeout=60):
    """Lista los objetos del bucket público (nombre, tamaño, md5Hash) paginando la API JSON."""
    items, token = [], None
    while True:
        url = f"{api_url}?prefix={prefix}&fields=items(name,size,md5Hash,updated),nextPageToken&maxResults=1000"
        if token:
            url += f"&pageToken={token}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = json.load(resp)
        items.extend(page.get("items", []))
        token = page.get("nextPageToken")
        if not token:
            return items


def check_coverage(catalog, pdet_codes, qc, check_id, source):
    """Cada municipio PDET debe quedar cubierto por al menos una partición de la fuente."""
    covered = set()
    for s in catalog["municipios"]:
        covered.update(s.split(";"))
    missing = sorted(set(pdet_codes) - covered)
    return qc.expect(check_id, f"Municipios PDET cubiertos por particiones de {source}", not missing,
                     f"{len(pdet_codes) - len(missing)}/{len(pdet_codes)}" + (f"; sin cobertura: {missing}" if missing else ""))


# --------------------------------------------------------------------------------------------
# Descarga y verificación
# --------------------------------------------------------------------------------------------

def md5_b64(path, chunk=1 << 20):
    """MD5 en base64, el formato de Content-MD5 (Azure) y de md5Hash (Cloud Storage)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return base64.b64encode(h.digest()).decode("ascii")


def gzip_stats(path, chunk=1 << 22):
    """Descomprime todo el archivo en streaming: detecta cortes o CRC malo y cuenta líneas."""
    lines = size = 0
    last = b"\n"
    with gzip.open(path, "rb") as f:
        while block := f.read(chunk):
            lines += block.count(b"\n")
            size += len(block)
            last = block[-1:]
    if size and last != b"\n":
        lines += 1
    return lines, size


def first_line(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.readline().rstrip("\n")


def head(url, timeout=60):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return dict(resp.headers)


def download(url, dest, retries=3, timeout=120, chunk=1 << 20):
    """Descarga por bloques a un .part y lo renombra al terminar. Reanuda con Range si se corta."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 1):
        start = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if start:
            req.add_header("Range", f"bytes={start}-")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                headers = dict(resp.headers)
                resumed = resp.status == 206
                if not resumed:
                    start = 0
                total = start + int(resp.headers.get("Content-Length", 0))
                with open(part, "ab" if resumed else "wb") as f:
                    while block := resp.read(chunk):
                        f.write(block)
            if total and part.stat().st_size != total:
                raise IOError(f"descarga incompleta: {part.stat().st_size} de {total} bytes")
            part.replace(dest)
            headers["Content-Length-Total"] = str(total)
            return headers
        except OSError as e:
            if attempt == retries:
                raise
            print(f"  [intento {attempt}/{retries}] {dest.name}: {e}")
            time.sleep(5 * attempt)


def write_qc(qc_json, qc_md, section, qc, extra=None):
    """Guarda una sección (seleccion o descarga) del reporte y regenera el Markdown con ambas."""
    qc_json, qc_md = Path(qc_json), Path(qc_md)
    data = json.loads(qc_json.read_text(encoding="utf-8")) if qc_json.exists() else {}
    data[section] = {"generado_utc": now_iso(), "resumen": qc.summary(), "controles": qc.checks, **(extra or {})}
    write_json(qc_json, data)

    titles = {"seleccion": "Selección de particiones (00d)", "descarga": "Descarga y verificación (00e)"}
    out = ["# Controles de calidad: adquisición de huellas de edificios", "",
           "Generado por `src/00d_select_building_partitions.py` y `src/00e_download_buildings.py`.", ""]
    for key in ("seleccion", "descarga"):
        if key not in data:
            continue
        sec = data[key]
        r = sec["resumen"]
        out += [f"## {titles[key]}", "", f"Corrida: {sec['generado_utc']}. Resultado: **{r[OK]} OK, "
                f"{r[AVISO]} AVISO, {r[FALLA]} FALLA**.", "", "| Id | Control | Resultado | Detalle |", "|---|---|---|---|"]
        for c in sec["controles"]:
            det = str(c["detalle"]).replace("|", "\\|")
            out.append(f"| {c['id']} | {c['control']} | {c['resultado']} | {det} |")
        out.append("")
    qc_md.parent.mkdir(parents=True, exist_ok=True)
    qc_md.write_text("\n".join(out), encoding="utf-8")
