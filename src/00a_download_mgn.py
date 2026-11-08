#!/usr/bin/env python3
"""Descarga el MGN2025 nivel municipio del geoportal del DANE y verifica su integridad.

Uso:
    python src/00a_download_mgn.py              # descarga (o reutiliza) y verifica
    python src/00a_download_mgn.py --force      # vuelve a descargar aunque ya exista
    python src/00a_download_mgn.py --verify     # solo verifica el ZIP que ya está en data/raw

Verificaciones: tamaño contra Content-Length y contra el valor fijado en config, SHA-256 contra el
valor fijado en config/acquisition.yaml, CRC de cada archivo del ZIP y presencia de los componentes
del shapefile. El resultado queda en docs/calidad/manifest_mgn.json.
"""
import argparse
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mgn_acquisition import load_config, now_iso, repo_path, sha256_file, write_json  # noqa: E402

SHP_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
USER_AGENT = "Proyecto-ABD/1.0 (descarga MGN DANE)"


def download(url, dest, retries=3, chunk=1 << 20):
    """Descarga por bloques a un .part y lo renombra al terminar. Reanuda si quedó a medias."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    headers = {}
    for attempt in range(1, retries + 1):
        start = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if start:
            req.add_header("Range", f"bytes={start}-")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                headers = dict(resp.headers)
                resumed = resp.status == 206
                if not resumed:
                    start = 0          # el servidor ignoró el Range: se empieza de cero
                total = start + int(resp.headers.get("Content-Length", 0))
                done, t0, last = start, time.time(), 0.0
                with open(part, "ab" if resumed else "wb") as f:
                    while block := resp.read(chunk):
                        f.write(block)
                        done += len(block)
                        if time.time() - last > 2:
                            last = time.time()
                            speed = (done - start) / max(last - t0, 1e-6) / 1e6
                            print(f"  {done / 1e6:7.1f} / {total / 1e6:.1f} MB  ({speed:.1f} MB/s)", end="\r")
            print()
            if total and part.stat().st_size != total:
                raise IOError(f"descarga incompleta: {part.stat().st_size} de {total} bytes")
            part.replace(dest)
            headers["Content-Length-Total"] = str(total)
            return headers
        except OSError as e:
            print(f"[intento {attempt}/{retries}] error: {e}")
            if attempt == retries:
                raise
            time.sleep(5 * attempt)


def check_zip(path, shp_name):
    """CRC de todo el ZIP y lista de archivos con tamaño."""
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f"[FALLA] CRC incorrecto en {bad} dentro de {path.name}")
        members = [{"name": i.filename, "bytes": i.file_size, "crc32": f"{i.CRC:08x}"} for i in z.infolist()]
    stem = Path(shp_name).stem
    names = {m["name"] for m in members}
    missing = [stem + ext for ext in SHP_PARTS if stem + ext not in names]
    if missing:
        raise SystemExit(f"[FALLA] faltan componentes del shapefile en el ZIP: {missing}")
    return members


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--force", action="store_true", help="descarga aunque el archivo ya exista")
    ap.add_argument("--verify", action="store_true", help="no descarga, solo verifica el ZIP local")
    args = ap.parse_args()

    cfg = load_config(args.config)
    m = cfg["mgn"]
    zpath = repo_path(m["zip"])
    manifest = {"fuente": "DANE - Marco Geoestadístico Nacional", "version": m["version"],
                "nivel": m["nivel"], "pagina": m["pagina"], "url": m["url"], "archivo": zpath.name}

    headers = {}
    if args.verify:
        if not zpath.exists():
            raise SystemExit(f"[FALLA] no existe {zpath}; ejecute sin --verify para descargarlo")
    elif zpath.exists() and not args.force:
        print(f"Ya existe {zpath.name}; se verifica sin descargar (use --force para repetir).")
    else:
        print(f"Descargando {m['url']}")
        t0 = time.time()
        headers = download(m["url"], zpath)
        manifest["descarga"] = {
            "fecha_utc": now_iso(),
            "segundos": round(time.time() - t0, 1),
            "http_last_modified": headers.get("Last-Modified"),
            "http_etag": headers.get("ETag"),
            "http_content_type": headers.get("Content-Type"),
        }

    size = zpath.stat().st_size
    digest = sha256_file(zpath)
    print(f"Tamaño: {size:,} bytes | SHA-256: {digest}")

    checks = []
    total = int(headers.get("Content-Length-Total", 0))
    if total:
        checks.append(("Tamaño = Content-Length del servidor", size == total, f"{size} / {total}"))
    if m.get("size_bytes"):
        checks.append(("Tamaño = valor fijado en config", size == int(m["size_bytes"]), f"{size} / {m['size_bytes']}"))
    if m.get("sha256"):
        checks.append(("SHA-256 = valor fijado en config", digest == m["sha256"].lower(), digest))
    else:
        print("[AVISO] config sin sha256: fije este valor en config/acquisition.yaml para las próximas corridas")

    members = check_zip(zpath, m["shapefile"])
    checks.append(("CRC de los archivos del ZIP", True, f"{len(members)} archivos sin errores"))
    checks.append(("Componentes del shapefile presentes", True, ", ".join(SHP_PARTS)))

    out_dir = repo_path(m["extract_dir"])
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out_dir)
    extracted = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)}
                 for p in sorted(out_dir.iterdir()) if p.is_file()]

    for desc, ok, det in checks:
        print(f"[{'OK' if ok else 'FALLA':5}] {desc}: {det}")

    manifest.update({
        "verificado_utc": now_iso(),
        "bytes": size,
        "sha256": digest,
        "sha256_esperado": m.get("sha256"),
        "controles": [{"control": d, "resultado": "OK" if ok else "FALLA", "detalle": det} for d, ok, det in checks],
        "contenido_zip": members,
        "extraido_en": m["extract_dir"],
        "archivos_extraidos": extracted,
    })
    prev = repo_path(cfg["output"]["manifest"])
    if "descarga" not in manifest and prev.exists():
        # Al solo verificar se conservan los datos HTTP de la descarga original.
        old = json.loads(prev.read_text(encoding="utf-8"))
        if old.get("sha256") == digest and "descarga" in old:
            manifest["descarga"] = old["descarga"]
    write_json(prev, manifest)
    print(f"Manifiesto: {prev.relative_to(repo_path('.'))}")

    if any(not ok for _, ok, _ in checks):
        raise SystemExit("[FALLA] la verificación no pasó; revise si el DANE publicó una versión nueva")
    print("Descarga verificada.")


if __name__ == "__main__":
    main()
