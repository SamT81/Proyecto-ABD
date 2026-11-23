#!/usr/bin/env python3
"""Entrega 4: mapas coropléticos y gráficos del área de techos aptos por municipio PDET.

Figuras (docs/mapas/, PNG):
  mapa_area_apta.png     área apta (km²) de Microsoft y de Google, con la misma escala de color
  mapa_diferencia.png    Google − Microsoft en km² de área apta (rojo: Google mayor, azul: Microsoft mayor)
  mapa_razon_conteo.png  razón Google/Microsoft del número de edificios (escala logarítmica, centrada en 1)
  top_area_apta.png      los N municipios con más área apta en cada fuente
Los municipios sin datos de Google se dibujan con rayado gris. Todas las figuras llevan la atribución de las licencias.

Uso:
    python src/05_make_maps.py
    python src/05_make_maps.py --input docs/eda/por_municipio.csv --geojson data/processed/pdet_municipios.geojson
    python src/05_make_maps.py --mongo        # lee los polígonos de la colección municipalities en vez del GeoJSON
"""
import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import LogNorm, PowerNorm, TwoSlopeNorm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CODE_KEYS = ("municipality_code", "divipola", "MPIO_CDPMP", "_id")


def load_config():
    return yaml.safe_load((ROOT / "config/maps.yaml").read_text(encoding="utf-8"))["maps"]


def read_results(path):
    """Formato ancho (una fila por municipio) a partir de results.csv (largo) o del CSV del EDA (ancho)."""
    df = pd.read_csv(path, dtype={"municipality_code": str})
    if "source" in df.columns:
        out = df[df.source == "microsoft"][["municipality_code", "name"]].drop_duplicates("municipality_code") \
            .set_index("municipality_code")
        for s, pre in (("microsoft", "ms_"), ("google", "g_")):
            sub = df[df.source == s].set_index("municipality_code")
            out[pre + "n"] = sub["building_count"]
            out[pre + "apt_km2"] = sub["suitable_area_m2"] / 1e6
            out[pre + "sin_datos"] = sub["sin_datos"].astype(str).str.lower().eq("true") if "sin_datos" in sub \
                else sub["building_count"] == 0
        out = out.reset_index()
    elif "ms_n_buildings" in df.columns:
        out = pd.DataFrame({"municipality_code": df.municipality_code, "name": df.get("name", ""),
                            "ms_n": df.ms_n_buildings.fillna(0), "ms_apt_km2": df.ms_area_apt_m2.fillna(0) / 1e6,
                            "g_n": df.g_n_buildings.fillna(0), "g_apt_km2": df.g_area_apt_m2.fillna(0) / 1e6})
        out["ms_sin_datos"] = out.ms_n == 0
        out["g_sin_datos"] = out.g_n == 0
    else:
        raise ValueError(f"{path}: formato desconocido (se esperaba results.csv o por_municipio.csv)")
    out["diff_km2"] = out.g_apt_km2 - out.ms_apt_km2
    out["ratio_n"] = out.g_n / out.ms_n.where(out.ms_n > 0)
    return out


def load_geometries(geojson=None, mongo=False):
    """GeoDataFrame con municipality_code y geometría en EPSG:4326."""
    if mongo:
        from pymongo import MongoClient
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        cfg = yaml.safe_load((ROOT / "config/params.yaml").read_text(encoding="utf-8"))
        db = MongoClient(cfg["mongo"]["uri"])[cfg["mongo"]["database"]]
        from shapely.geometry import shape
        docs = list(db.municipalities.find({}, {"geometry": 1, "name": 1}))
        return gpd.GeoDataFrame({"municipality_code": [d["_id"] for d in docs]},
                                geometry=[shape(d["geometry"]) for d in docs], crs="EPSG:4326")
    gdf = gpd.read_file(geojson)
    key = next((k for k in CODE_KEYS if k in gdf.columns), None)
    if key is None:
        raise ValueError(f"{geojson}: no hay columna con el código del municipio ({', '.join(CODE_KEYS)})")
    gdf = gdf.rename(columns={key: "municipality_code"})
    gdf["municipality_code"] = gdf["municipality_code"].astype(str).str.zfill(5)
    return gdf[["municipality_code", "geometry"]].to_crs("EPSG:4326")


def _draw(ax, gdf, column, cmap, norm, nodata_col, title):
    ok = gdf[~gdf[nodata_col].fillna(True).astype(bool)]
    miss = gdf[gdf[nodata_col].fillna(True).astype(bool)]
    if len(miss):
        miss.plot(ax=ax, facecolor="#e6e6e6", edgecolor="#888888", hatch="///", linewidth=0.3)
    ok.plot(ax=ax, column=column, cmap=cmap, norm=norm, edgecolor="white", linewidth=0.15)
    ax.set_title(title, fontsize=11)
    ax.set_axis_off()
    ax.set_aspect("equal")


def _colorbar(fig, ax, cmap, norm, label):
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.02)
    cb.set_label(label, fontsize=9)


def _footer(fig, text):
    fig.text(0.5, 0.01, text, ha="center", va="bottom", fontsize=6.5, color="#444444", wrap=True)


def map_area_apta(gdf, out, attribution, dpi):
    vmax = float(max(gdf.ms_apt_km2.max(), gdf.g_apt_km2.max()))
    norm = PowerNorm(gamma=0.4, vmin=0, vmax=vmax)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4))
    _draw(axes[0], gdf, "ms_apt_km2", "YlOrRd", norm, "ms_sin_datos", "Microsoft")
    _draw(axes[1], gdf, "g_apt_km2", "YlOrRd", norm, "g_sin_datos", "Google (rayado: sin datos)")
    _colorbar(fig, axes, "YlOrRd", norm, "Área de techos aptos (km²)")
    fig.suptitle("Área de techos aptos por municipio PDET", fontsize=13)
    _footer(fig, attribution)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def map_diferencia(gdf, out, attribution, dpi):
    lim = float(np.nanmax(np.abs(gdf.diff_km2))) or 1.0
    norm = TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim)
    fig, ax = plt.subplots(figsize=(7, 7))
    _draw(ax, gdf, "diff_km2", "RdBu_r", norm, "g_sin_datos", "Google − Microsoft, área apta (km²)")
    _colorbar(fig, ax, "RdBu_r", norm, "km² (rojo: Google mayor; azul: Microsoft mayor)")
    _footer(fig, attribution)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def map_razon(gdf, out, attribution, dpi):
    r = gdf.ratio_n.replace([np.inf, -np.inf], np.nan)
    hi = float(np.nanmax(r)) if r.notna().any() else 2.0
    lo = float(np.nanmin(r[r > 0])) if (r > 0).any() else 0.5
    span = max(hi, 1 / max(lo, 1e-6), 1.01)
    gdf = gdf.assign(ratio_n=r)
    norm = LogNorm(vmin=1 / span, vmax=span)
    fig, ax = plt.subplots(figsize=(7, 7))
    _draw(ax, gdf, "ratio_n", "PuOr", norm, "g_sin_datos", "Razón Google / Microsoft del número de edificios")
    _colorbar(fig, ax, "PuOr", norm, "razón (1 = igual; escala logarítmica)")
    _footer(fig, attribution)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def chart_top(df, out, n, attribution, dpi):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharex=True)
    for ax, (col, label, color) in zip(axes, (("ms_apt_km2", "Microsoft", "#1f77b4"), ("g_apt_km2", "Google", "#d95f02"))):
        top = df.nlargest(n, col).iloc[::-1]
        ax.barh(top["name"].astype(str), top[col], color=color)
        ax.set_title(f"{label}: {n} municipios con más área apta", fontsize=10)
        ax.set_xlabel("Área de techos aptos (km²)")
        ax.tick_params(axis="y", labelsize=8)
    _footer(fig, attribution)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def make_all(df, geoms, out_dir, cfg):
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = geoms.merge(df, on="municipality_code", how="left")
    missing = sorted(set(df.municipality_code) - set(geoms.municipality_code))
    if missing:
        print(f"Aviso: {len(missing)} municipios de los resultados no tienen polígono: {missing[:5]}")
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=geoms.crs)
    for c in ("ms_sin_datos", "g_sin_datos"):
        gdf[c] = gdf[c].fillna(True).astype(bool)
    att, dpi = cfg["attribution"], cfg["dpi"]
    files = {"mapa_area_apta.png": lambda p: map_area_apta(gdf, p, att, dpi),
             "mapa_diferencia.png": lambda p: map_diferencia(gdf, p, att, dpi),
             "mapa_razon_conteo.png": lambda p: map_razon(gdf, p, att, dpi),
             "top_area_apta.png": lambda p: chart_top(df, p, cfg["top_n"], att, dpi)}
    for name, fn in files.items():
        fn(out_dir / name)
        print("  ", out_dir / name)
    return list(files)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--geojson")
    ap.add_argument("--mongo", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    path = Path(a.input) if a.input else ROOT / cfg["input_csv"]
    if not path.exists():
        path = ROOT / cfg["fallback_csv"]
        print(f"Aviso: no existe {cfg['input_csv']}; se usa {cfg['fallback_csv']} (EDA de la Entrega 3)")
    df = read_results(path)
    gj = Path(a.geojson) if a.geojson else ROOT / cfg["municipalities_geojson"]
    if not a.mongo and not gj.exists():
        raise SystemExit(f"No existe {gj}. Pida a Alejandro data/processed/pdet_municipios.geojson o use --mongo")
    geoms = load_geometries(gj, a.mongo)
    print(f"{len(df)} municipios con datos, {len(geoms)} polígonos")
    make_all(df, geoms, ROOT / cfg["out_dir"], cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
