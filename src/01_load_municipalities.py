"""ETL Entrega 2: Validación de integridad y carga de municipios PDET en MongoDB."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

from utils.geo_integrity import (
    build_ingestion_log_document,
    build_municipality_document,
    compute_sha256,
    normalize_divipola,
    prepare_municipalities_gdf,
)

EXPECTED_PDET_COUNT = 170

DIVIPOLA_CANDIDATES = ("MPIO_CDPMP", "COD_MPIO", "DIVIPOLA", "divipola", "codigo_dane")
NAME_CANDIDATES = ("MPIO_CNMBR", "NOM_MPIO", "NOMBRE_MPIO", "name", "municipio")
DEPT_NAME_CANDIDATES = ("DPTO_CNMBR", "NOM_DPTO", "department_name", "departamento")
SUBREGION_CANDIDATES = ("SUBREGION", "SUBREGION_PDET", "pdet_subregion", "subregion")


def load_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_column(columns: list[str], candidates: tuple[str, ...], label: str) -> str:
    col_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in col_map:
            return col_map[cand.lower()]
    raise KeyError(f"No se encontró columna para '{label}'. Disponibles: {columns}")


def standardize_schema(
    gdf: gpd.GeoDataFrame,
    pdet_catalog_path: Path | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Estandariza nombres de columnas y filtra los 170 municipios PDET si se entrega catálogo."""
    rows_read = len(gdf)
    cols = list(gdf.columns)

    div_col = resolve_column(cols, DIVIPOLA_CANDIDATES, "divipola")
    name_col = resolve_column(cols, NAME_CANDIDATES, "name")
    dept_col = resolve_column(cols, DEPT_NAME_CANDIDATES, "department_name")

    work = gdf.copy()
    work["divipola"] = work[div_col].apply(normalize_divipola)
    work["name"] = work[name_col].astype(str).str.strip()
    work["department_name"] = work[dept_col].astype(str).str.strip()

    if pdet_catalog_path is not None:
        catalog = pd.read_csv(pdet_catalog_path, dtype=str)
        cat_cols = list(catalog.columns)
        cat_div = resolve_column(cat_cols, DIVIPOLA_CANDIDATES, "divipola catálogo")
        cat_sub = resolve_column(cat_cols, SUBREGION_CANDIDATES, "subregión PDET")

        catalog["divipola"] = catalog[cat_div].apply(normalize_divipola)
        catalog["pdet_subregion"] = catalog[cat_sub].astype(str).str.strip()
        catalog = catalog[["divipola", "pdet_subregion"]].drop_duplicates(subset=["divipola"])

        work = work.merge(catalog, on="divipola", how="inner")
    else:
        sub_col = resolve_column(cols, SUBREGION_CANDIDATES, "pdet_subregion")
        work["pdet_subregion"] = work[sub_col].astype(str).str.strip()

    keep_cols = ["divipola", "name", "department_name", "pdet_subregion", "geometry"]
    return gpd.GeoDataFrame(work[keep_cols], geometry="geometry", crs=gdf.crs), rows_read


def validate_pdet_integrity(gdf: gpd.GeoDataFrame) -> None:
    """Verifica conteo exacto de 170 municipios PDET, unicidad y ausencia de nulos."""
    if len(gdf) != EXPECTED_PDET_COUNT:
        raise ValueError(
            f"Integridad fallida: se esperaban {EXPECTED_PDET_COUNT} municipios PDET, "
            f"pero se obtuvieron {len(gdf)}."
        )

    if gdf["divipola"].nunique() != EXPECTED_PDET_COUNT:
        dups = gdf[gdf.duplicated(subset=["divipola"], keep=False)]["divipola"].tolist()
        raise ValueError(f"Códigos DIVIPOLA duplicados detectados: {dups}")

    required_fields = ["divipola", "name", "department_name", "pdet_subregion", "area_km2", "geometry"]
    for field in required_fields:
        nulls = gdf[field].isna().sum()
        if nulls > 0:
            raise ValueError(f"El campo obligatorio '{field}' tiene {nulls} valores nulos.")

    if (gdf["area_km2"] <= 0).any():
        raise ValueError("Existen municipios con área calculada menor o igual a 0 km².")


def run_etl(
    mgn_path: Path,
    pdet_catalog_path: Path | None,
    config_path: Path,
    layer: str | None = None,
    dry_run: bool = False,
) -> None:
    load_dotenv()
    cfg = load_config(config_path)

    mongo_uri = os.getenv("MONGO_URI", cfg["mongo"]["uri"])
    db_name = os.getenv("MONGO_DB", cfg["mongo"]["database"])
    area_crs = cfg["crs"]["area"]
    storage_crs = cfg["crs"]["storage"]
    mgn_version = cfg["mgn"]["version"]

    if not mgn_path.exists():
        raise FileNotFoundError(f"No existe el archivo espacial: {mgn_path}")

    checksum = compute_sha256(mgn_path)
    print(f"[INFO] Archivo: {mgn_path.name} | SHA-256: {checksum}")

    read_kwargs = {"layer": layer} if layer else {}
    raw_gdf = gpd.read_file(mgn_path, **read_kwargs)

    std_gdf, rows_read = standardize_schema(raw_gdf, pdet_catalog_path)
    clean_gdf, rejected_geom = prepare_municipalities_gdf(
        std_gdf,
        area_crs=area_crs,
        storage_crs=storage_crs,
    )
    validate_pdet_integrity(clean_gdf)

    documents = [
        build_municipality_document(row, mgn_version=mgn_version)
        for _, row in clean_gdf.iterrows()
    ]
    rows_rejected = rows_read - len(documents)

    print(
        f"[OK] Validación superada: {len(documents)} municipios PDET listos "
        f"(leídos={rows_read}, descartados={rows_rejected}, geom_inválidas={rejected_geom})."
    )

    if dry_run:
        print("[DRY-RUN] Modo simulación activo: no se escribió en MongoDB.")
        return

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    operations = [
        ReplaceOne({"_id": doc["_id"]}, doc, upsert=True)
        for doc in documents
    ]
    result = db.municipalities.bulk_write(operations, ordered=False)
    inserted_or_updated = result.upserted_count + result.modified_count + result.matched_count

    log_doc = build_ingestion_log_document(
        dataset=mgn_version.lower(),
        file_name=mgn_path.name,
        rows_read=rows_read,
        rows_inserted=len(documents),
        rows_rejected=rows_rejected,
        checksum=checksum,
    )
    db.ingestion_log.insert_one(log_doc)
    client.close()

    print(
        f"[OK] Ingesta completada en '{db_name}.municipalities' "
        f"({inserted_or_updated} documentos procesados) y bitácora registrada."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida e ingesta los 170 municipios PDET en MongoDB."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/mgn_pdet_2025.gpkg"),
        help="Ruta al archivo espacial MGN (GeoPackage, Shapefile o GeoJSON).",
    )
    parser.add_argument(
        "--pdet-csv",
        type=Path,
        default=None,
        help="CSV opcional con catálogo oficial de 170 municipios PDET y subregión.",
    )
    parser.add_argument(
        "--layer",
        type=str,
        default=None,
        help="Nombre de la capa municipal si el archivo tiene múltiples capas.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/params.yaml"),
        help="Ruta al archivo de configuración YAML.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta validación y formateo sin escribir en MongoDB.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        run_etl(
            mgn_path=args.input,
            pdet_catalog_path=args.pdet_csv,
            config_path=args.config,
            layer=args.layer,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
