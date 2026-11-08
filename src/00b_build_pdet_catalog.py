#!/usr/bin/env python3
"""Convierte el listado de municipios PDET de la ART (Excel) en el catálogo CSV del proyecto.

Uso:
    python src/00b_build_pdet_catalog.py

Lee config/pdet/MunicipiosPDET.xlsx y escribe config/pdet/pdet_municipios.csv con los códigos
DIVIPOLA a 5 dígitos (en el Excel los de Antioquia aparecen como 5490 en vez de 05490) y el id de
subregión. El CSV se versiona en el repo y también sirve como --pdet-csv del ETL.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mgn_acquisition import QCReport, catalog_from_rows, check_catalog, load_config, repo_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--sheet", default=0, help="hoja del Excel (por defecto la primera)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    src = repo_path(cfg["pdet"]["source_xlsx"])
    dst = repo_path(cfg["pdet"]["catalog_csv"])

    raw = pd.read_excel(src, sheet_name=args.sheet, dtype=str)
    cat = catalog_from_rows(raw.to_dict("records"))

    qc = QCReport()
    check_catalog(cat, qc, cfg["pdet"]["expected_municipalities"], cfg["pdet"]["expected_subregions"])
    if qc.failed:
        raise SystemExit("[FALLA] el listado PDET no pasó los controles; no se escribe el CSV")

    dst.parent.mkdir(parents=True, exist_ok=True)
    cat.to_csv(dst, index=False, encoding="utf-8")
    print(f"\n{len(cat)} municipios en {cat['pdet_subregion'].nunique()} subregiones -> {dst.relative_to(repo_path('.'))}")
    print(cat.groupby(["pdet_subregion_id", "pdet_subregion"]).size().to_string())


if __name__ == "__main__":
    main()
