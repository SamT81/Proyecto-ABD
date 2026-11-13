#!/usr/bin/env python3
"""Descarga y verifica las particiones de huellas de edificios listadas en el catálogo PDET.

Uso:
    python src/00e_download_buildings.py                       # ambas fuentes
    python src/00e_download_buildings.py --source microsoft    # solo una fuente
    python src/00e_download_buildings.py --verify              # no descarga, solo verifica lo que hay
    python src/00e_download_buildings.py --limit 3             # prueba rápida con 3 archivos por fuente

Verificaciones por archivo: tamaño contra Content-Length, MD5 contra el valor oficial (md5Hash del bucket
de Google o Content-MD5 del servidor de Microsoft), integridad gzip descomprimiendo todo el archivo,
conteo de registros y formato de la primera línea. El resultado queda en docs/calidad/manifest_buildings.json
y en docs/calidad/qc_buildings_acquisition.md. Un archivo que ya existe y cuyo MD5 coincide no se vuelve a bajar.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildings_acquisition as ba  # noqa: E402

GOOGLE_HEADER = "latitude,longitude,area_in_meters,confidence,geometry,full_plus_code"


def check_format(source, line):
    """La primera línea dice si el archivo es el esperado (cabecera CSV de Google o Feature GeoJSON de Microsoft)."""
    if source == "google":
        return line.strip() == GOOGLE_HEADER, line[:80]
    try:
        feat = json.loads(line)
        ok = feat.get("type") == "Feature" and feat["geometry"]["type"] in ("Polygon", "MultiPolygon")
        return ok, f"Feature {feat['geometry']['type']}, propiedades {sorted(feat.get('properties', {}))}"
    except (ValueError, KeyError, TypeError) as e:
        return False, f"no es GeoJSON: {e}"


def process(row, raw_dir, verify_only, dl_cfg, previous):
    """Descarga (si hace falta) y verifica un archivo. Devuelve la entrada del manifiesto."""
    dest = raw_dir / row.file_name
    entry = {"source": row.source, "partition_id": row.partition_id, "archivo": row.file_name, "url": row.url}
    headers, t0 = {}, time.time()

    expected_md5 = row.md5_b64 if isinstance(row.md5_b64, str) and row.md5_b64 else None
    if not verify_only:
        # HEAD antes de descargar: tamaño y fecha del servidor y, en Microsoft, el MD5 (Content-MD5) para
        # saber si el archivo local sigue vigente. Google publica su MD5 en el listado del bucket (catálogo).
        h = ba.head(row.url, dl_cfg["timeout_s"])
        if row.source == "microsoft":
            expected_md5 = h.get("Content-MD5")
        entry["bytes_servidor"] = int(h.get("Content-Length", 0)) or None
        entry["http_last_modified"] = h.get("Last-Modified")
        entry["http_etag"] = h.get("ETag")
    elif row.source == "microsoft":
        expected_md5 = (previous.get(row.file_name) or {}).get("md5_esperado")

    local_md5 = ba.md5_b64(dest) if dest.exists() else None
    if verify_only and not dest.exists():
        entry.update({"estado": "faltante", "controles": {}})
        return entry
    if not verify_only and (local_md5 is None or (expected_md5 and local_md5 != expected_md5)):
        headers = ba.download(row.url, dest, dl_cfg["retries"], dl_cfg["timeout_s"])
        entry["descarga_utc"] = ba.now_iso()
        entry["segundos"] = round(time.time() - t0, 1)
        entry["bytes_servidor"] = int(headers.get("Content-Length-Total", 0)) or None
        expected_md5 = expected_md5 or headers.get("Content-MD5")
        local_md5 = ba.md5_b64(dest)
        entry["estado"] = "descargado"
    else:
        entry["estado"] = "reutilizado"
        old = previous.get(row.file_name) or {}
        for k in ("descarga_utc", "segundos", "bytes_servidor", "http_last_modified", "http_etag"):
            entry.setdefault(k, old.get(k))
        if not entry.get("descarga_utc"):
            # Sin manifiesto previo, la fecha de descarga es la de escritura del archivo local.
            mtime = datetime.fromtimestamp(dest.stat().st_mtime, timezone.utc).replace(microsecond=0)
            entry["descarga_utc"] = mtime.isoformat()

    size = dest.stat().st_size
    checks = {}
    total = entry.get("bytes_servidor")
    checks["tamano_servidor"] = (size == total) if total else None
    approx = int(row.size_bytes)
    # Microsoft publica "4.5MB": el tamaño real puede estar hasta una décima de unidad por encima.
    checks["tamano_catalogo"] = (size == approx) if row.size_exact else \
        -ba.size_tolerance(approx) <= size - approx <= ba.size_tolerance(approx) * 2
    checks["md5"] = (local_md5 == expected_md5) if expected_md5 else None
    try:
        lines, raw_bytes = ba.gzip_stats(dest)
        checks["gzip"] = True
    except (OSError, EOFError) as e:
        lines, raw_bytes = 0, 0
        checks["gzip"] = False
        entry["error_gzip"] = str(e)
    fmt_ok, fmt_detail = check_format(row.source, ba.first_line(dest)) if checks["gzip"] else (False, "")
    checks["formato"] = fmt_ok

    entry.update({
        "bytes": size,
        "bytes_descomprimidos": raw_bytes,
        "registros": lines - 1 if row.source == "google" else lines,
        "md5_b64": local_md5,
        "md5_esperado": expected_md5,
        "sha256": ba.sha256_file(dest),
        "formato": fmt_detail,
        "controles": checks,
    })
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--source", choices=["microsoft", "google"])
    ap.add_argument("--verify", action="store_true", help="no descarga, solo verifica los archivos locales")
    ap.add_argument("--limit", type=int, help="máximo de archivos por fuente (pruebas)")
    ap.add_argument("--workers", type=int)
    args = ap.parse_args()

    cfg = ba.load_buildings_config(args.config)
    cat_path = ba.repo_path(cfg["selection"]["catalog_csv"])
    if not cat_path.exists():
        raise SystemExit(f"[FALLA] no existe {cat_path}; ejecute antes src/00d_select_building_partitions.py")
    catalog = pd.read_csv(cat_path, dtype={"partition_id": str, "md5_b64": str}, keep_default_na=False)
    if args.source:
        catalog = catalog[catalog["source"] == args.source]
    if args.limit:
        catalog = catalog.groupby("source", group_keys=False).head(args.limit)

    man_path = ba.repo_path(cfg["output"]["manifest"])
    old = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    previous = {a["archivo"]: a for a in old.get("archivos", [])}

    dl_cfg = cfg["download"]
    workers = args.workers or dl_cfg["workers"]
    print(f"{len(catalog)} archivos ({catalog['size_bytes'].sum() / 1e6:,.1f} MB) con {workers} hilos")
    entries, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(process, row, ba.repo_path(cfg["sources"][row.source]["raw_dir"]),
                            args.verify, dl_cfg, previous): row for row in catalog.itertuples()}
        for i, fut in enumerate(as_completed(futs), 1):
            row = futs[fut]
            try:
                e = fut.result()
            except Exception as exc:  # noqa: BLE001
                e = {"source": row.source, "partition_id": row.partition_id, "archivo": row.file_name,
                     "url": row.url, "estado": "error", "error": str(exc)[:300], "controles": {}}
            entries.append(e)
            bad = [k for k, v in e["controles"].items() if v is False]
            tag = "FALLA" if bad or e["estado"] in ("error", "faltante") else "OK"
            print(f"[{i:3}/{len(catalog)}] [{tag:5}] {e['source']:9} {e['partition_id']:10} {e['estado']:11} "
                  f"{e.get('bytes', 0) / 1e6:8.1f} MB {e.get('registros', 0):>11,} reg." + (f"  {bad}" if bad else ""))

    # Se conservan las entradas de archivos que no se procesaron en esta corrida (--source o --limit).
    done = {e["archivo"] for e in entries}
    entries += [a for name, a in previous.items() if name not in done]
    entries.sort(key=lambda e: (e["source"], e["partition_id"]))

    qc = ba.QCReport()
    full = pd.read_csv(cat_path, dtype={"partition_id": str}, keep_default_na=False)
    controles = (("tamano_servidor", "Tamaño = Content-Length del servidor"),
                 ("tamano_catalogo", "Tamaño = tamaño publicado en el índice"),
                 ("md5", "MD5 = valor oficial de la fuente"),
                 ("gzip", "Integridad gzip (descompresión completa)"),
                 ("formato", "Formato de la primera línea"))
    for source in ("microsoft", "google"):
        ids = set(full.loc[full["source"] == source, "partition_id"])
        es = [e for e in entries if e["source"] == source and e["partition_id"] in ids]
        okd = [e for e in es if e["estado"] in ("descargado", "reutilizado")]
        base = f"DL-{source[0].upper()}"
        faltan = sorted(ids - {e["partition_id"] for e in okd})
        qc.expect(f"{base}1", f"Archivos de {source} disponibles", not faltan,
                  f"{len(okd)}/{len(ids)}" + (f"; faltan o con error: {faltan[:20]}" if faltan else ""))
        for j, (key, desc) in enumerate(controles, 2):
            checked = [(e["partition_id"], e["controles"][key]) for e in okd if e["controles"].get(key) is not None]
            bad = [p for p, v in checked if v is False]
            # El tamaño del índice de Microsoft viene redondeado: una diferencia ahí se revisa, no bloquea.
            nivel = ba.AVISO if key.startswith("tamano") else ba.FALLA
            qc.expect(f"{base}{j}", f"{desc} ({source})", not bad,
                      f"{len(checked) - len(bad)}/{len(checked)} verificados" + (f"; fallan: {bad}" if bad else ""),
                      nivel=nivel)
        regs = sum(e.get("registros", 0) for e in okd)
        mb = sum(e.get("bytes", 0) for e in okd) / 1e6
        empty = [e["partition_id"] for e in okd if not e.get("registros")]
        qc.expect(f"{base}7", f"Registros en los archivos de {source}", not empty,
                  f"{regs:,} registros en {mb:,.1f} MB" + (f"; vacíos: {empty}" if empty else ""), nivel=ba.AVISO)

    manifest = {
        "fuentes": {k: {c: v for c, v in s.items() if c in ("nombre", "licencia", "pagina", "formato")}
                    for k, s in cfg["sources"].items()},
        "catalogo": cfg["selection"]["catalog_csv"],
        "verificado_utc": ba.now_iso(),
        "segundos": round(time.time() - t0, 1),
        "totales": {s: {"archivos": sum(1 for e in entries if e["source"] == s),
                        "bytes": sum(e.get("bytes", 0) for e in entries if e["source"] == s),
                        "registros": sum(e.get("registros", 0) for e in entries if e["source"] == s)}
                    for s in ("microsoft", "google")},
        "archivos": entries,
    }
    ba.write_json(man_path, manifest)
    o = cfg["output"]
    ba.write_qc(ba.repo_path(o["qc_json"]), ba.repo_path(o["qc_md"]), "descarga", qc,
                {"totales": manifest["totales"]})
    s = qc.summary()
    print(f"\nManifiesto: {man_path.relative_to(ba.repo_path('.'))}")
    print(f"Controles: {s[ba.OK]} OK, {s[ba.AVISO]} AVISO, {s[ba.FALLA]} FALLA ({manifest['segundos']} s)")
    if qc.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
