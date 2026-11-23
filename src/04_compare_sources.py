#!/usr/bin/env python3
"""Entrega 4: comparación entre Microsoft y Google por municipio PDET.

Lee results.csv (src/03_build_results.py) y calcula, por municipio: diferencia absoluta y relativa de conteo y de área
apta, razón Google/Microsoft; y en conjunto: correlaciones (Pearson y Spearman), municipios con mayor discrepancia,
ranking por área apta y concordancia entre rankings, y un resumen por subregión PDET. Los municipios donde Google no
tiene datos (sin_datos) se muestran aparte y no entran en correlaciones ni en discrepancias relativas.

Uso:
    python src/04_compare_sources.py
    python src/04_compare_sources.py --input docs/eda/por_municipio.csv    # también acepta el CSV del EDA (Entrega 3)
Salida: docs/comparacion/ (CSV, comparacion.md, resumen_comparacion.json y tablas .tex)
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
METRICS = ["building_count", "total_roof_area_m2", "suitable_count", "suitable_area_m2"]


def load_config():
    return yaml.safe_load((ROOT / "config/comparison.yaml").read_text(encoding="utf-8"))["comparison"]


def read_results(path):
    """Devuelve el formato largo (una fila por municipio y fuente). Acepta results.csv o el CSV ancho del EDA."""
    df = pd.read_csv(path, dtype={"municipality_code": str})
    if "source" in df.columns:
        if "sin_datos" not in df.columns:
            df["sin_datos"] = False
        df["sin_datos"] = df["sin_datos"].astype(str).str.lower().eq("true")
        return df
    if "ms_n_buildings" not in df.columns:
        raise ValueError(f"{path}: formato desconocido (se esperaba results.csv o por_municipio.csv)")
    rows = []
    for s, pre in (("microsoft", "ms_"), ("google", "g_")):
        part = df[["municipality_code", "name", "pdet_subregion"]].copy()
        part["source"] = s
        part["building_count"] = df[pre + "n_buildings"].fillna(0)
        part["total_roof_area_m2"] = df[pre + "area_total_m2"].fillna(0)
        part["suitable_count"] = df[pre + "n_apt"].fillna(0)
        part["suitable_area_m2"] = df[pre + "area_apt_m2"].fillna(0)
        part["sin_datos"] = part["building_count"] == 0
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def compare(long_df):
    """Una fila por municipio con las dos fuentes lado a lado y sus diferencias."""
    keep = ["municipality_code", "name", "pdet_subregion"]
    keep = [c for c in keep if c in long_df.columns]
    base = long_df[long_df.source == "microsoft"][keep].drop_duplicates("municipality_code").set_index("municipality_code")
    for s, pre in (("microsoft", "ms_"), ("google", "g_")):
        sub = long_df[long_df.source == s].set_index("municipality_code")
        for m in METRICS:
            base[pre + m] = sub[m]
            if m.endswith("_count"):
                base[pre + m] = base[pre + m].fillna(0).astype(int)
        base[pre + "sin_datos"] = sub["sin_datos"]
    base = base.reset_index()
    base["g_sin_datos"] = base["g_sin_datos"].fillna(True).astype(bool)
    base["ms_sin_datos"] = base["ms_sin_datos"].fillna(True).astype(bool)
    base["diff_count"] = base["g_building_count"] - base["ms_building_count"]
    base["rel_diff_count"] = base["diff_count"] / base["ms_building_count"].where(base["ms_building_count"] > 0)
    base["diff_apt_km2"] = (base["g_suitable_area_m2"] - base["ms_suitable_area_m2"]) / 1e6
    base["rel_diff_apt"] = ((base["g_suitable_area_m2"] - base["ms_suitable_area_m2"])
                            / base["ms_suitable_area_m2"].where(base["ms_suitable_area_m2"] > 0))
    base["ratio_g_ms_count"] = base["g_building_count"] / base["ms_building_count"].where(base["ms_building_count"] > 0)
    base["ratio_g_ms_apt"] = base["g_suitable_area_m2"] / base["ms_suitable_area_m2"].where(base["ms_suitable_area_m2"] > 0)
    for s in ("ms", "g"):
        base[f"{s}_apt_km2"] = base[f"{s}_suitable_area_m2"] / 1e6
        base[f"{s}_rank_apt"] = base[f"{s}_suitable_area_m2"].rank(ascending=False, method="min").astype(int)
    return base


def summarize(c, cfg):
    both = c[~c.g_sin_datos & ~c.ms_sin_datos]
    out = {"municipios": int(len(c)), "municipios_comparables": int(len(both)),
           "municipios_sin_datos_google": c[c.g_sin_datos].municipality_code.tolist()}
    for s, pre in (("microsoft", "ms_"), ("google", "g_")):
        out[s] = {"edificios": int(c[pre + "building_count"].sum()),
                  "area_total_km2": round(c[pre + "total_roof_area_m2"].sum() / 1e6, 2),
                  "techos_aptos": int(c[pre + "suitable_count"].sum()),
                  "area_apta_km2": round(c[pre + "suitable_area_m2"].sum() / 1e6, 2)}
    if len(both) > 2:
        out["correlacion"] = {
            "conteo_pearson": round(both.g_building_count.corr(both.ms_building_count), 4),
            "conteo_spearman": round(both.g_building_count.rank().corr(both.ms_building_count.rank()), 4),
            "area_apta_pearson": round(both.g_suitable_area_m2.corr(both.ms_suitable_area_m2), 4),
            "area_apta_spearman": round(both.g_suitable_area_m2.rank().corr(both.ms_suitable_area_m2.rank()), 4)}
        out["razon_google_microsoft"] = {
            "conteo_mediana": round(float(both.ratio_g_ms_count.median()), 3),
            "area_apta_mediana": round(float(both.ratio_g_ms_apt.median()), 3),
            "municipios_google_mayor_conteo": int((both.diff_count > 0).sum()),
            "municipios_google_mayor_area_apta": int((both.diff_apt_km2 > 0).sum()),
            "error_relativo_abs_medio_area_apta": round(float(both.rel_diff_apt.abs().mean()), 3)}
        k = cfg["concordance_top_k"]
        top_ms = set(both.nsmallest(k, "ms_rank_apt").municipality_code)
        top_g = set(both.nsmallest(k, "g_rank_apt").municipality_code)
        out["concordancia_ranking"] = {"k": k, "interseccion_top_k": len(top_ms & top_g),
                                       "spearman_rangos": round(both.ms_rank_apt.corr(both.g_rank_apt, method="spearman"), 4)}
    return out


def top_discrepancies(c, cfg):
    both = c[~c.g_sin_datos & ~c.ms_sin_datos]
    n = cfg["top_n"]
    cols = ["municipality_code", "name", "ms_building_count", "g_building_count", "ms_apt_km2", "g_apt_km2",
            "diff_apt_km2", "rel_diff_apt"]
    cols = [x for x in cols if x in both.columns]
    absolute = both.reindex(both.diff_apt_km2.abs().sort_values(ascending=False).index).head(n)[cols]
    elig = both[both.ms_building_count >= cfg["min_buildings_relative"]]
    relative = elig.reindex(elig.rel_diff_apt.abs().sort_values(ascending=False).index).head(n)[cols]
    return absolute, relative


def ranking(c, cfg):
    n = cfg["ranking_n"]
    cols = ["name", "municipality_code", "apt_km2"]
    ms = c.nsmallest(n, "ms_rank_apt")[["ms_rank_apt", "name", "municipality_code", "ms_apt_km2"]]
    g = c.nsmallest(n, "g_rank_apt")[["g_rank_apt", "name", "municipality_code", "g_apt_km2"]]
    return ms, g


def by_subregion(c):
    if "pdet_subregion" not in c.columns:
        return pd.DataFrame()
    g = c.groupby("pdet_subregion").agg(
        municipios=("municipality_code", "count"), ms_edificios=("ms_building_count", "sum"),
        g_edificios=("g_building_count", "sum"), ms_apt_km2=("ms_apt_km2", "sum"), g_apt_km2=("g_apt_km2", "sum"))
    g["ratio_g_ms_apt"] = g.g_apt_km2 / g.ms_apt_km2.where(g.ms_apt_km2 > 0)
    return g.sort_values("ms_apt_km2", ascending=False).round(3).reset_index()


def tex_escape(s):
    return str(s).replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def to_tex(df, fmt, header):
    lines = [r"\begin{tabular}{" + fmt + "}", r"\toprule", " & ".join(header) + r" \\", r"\midrule"]
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append("--" if pd.isna(v) else f"{v:,.2f}".replace(",", r"\,"))
            elif isinstance(v, (int,)) or hasattr(v, "item") and not isinstance(v, str):
                cells.append(f"{int(v):,}".replace(",", r"\,"))
            else:
                cells.append(tex_escape(v))
        lines.append(" & ".join(cells) + r" \\")
    return "\n".join(lines + [r"\bottomrule", r"\end{tabular}", ""])


def write_outputs(out_dir, c, summary, absolute, relative, rank_ms, rank_g, sub):
    out_dir.mkdir(parents=True, exist_ok=True)
    c.round(4).to_csv(out_dir / "comparacion_municipios.csv", index=False)
    (out_dir / "resumen_comparacion.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not sub.empty:
        sub.to_csv(out_dir / "por_subregion.csv", index=False)
    hdr = ["Municipio", "Edif. MS", "Edif. Google", "Apta MS (km$^2$)", "Apta Google (km$^2$)", "Dif. (km$^2$)", "Dif. rel."]
    for name, df in (("top_discrepancias_abs", absolute), ("top_discrepancias_rel", relative)):
        d = df.drop(columns=["municipality_code"]).copy()
        d["rel_diff_apt"] = d["rel_diff_apt"] * 100
        hdr_p = hdr[:-1] + ["Dif. rel. (\\%)"]
        (out_dir / f"{name}.tex").write_text(to_tex(d, "lrrrrrr", hdr_p), encoding="utf-8")
        df.round(4).to_csv(out_dir / f"{name}.csv", index=False)
    r = pd.DataFrame({"rank": range(1, len(rank_ms) + 1), "ms": rank_ms.name.values, "ms_km2": rank_ms.ms_apt_km2.values,
                      "g": rank_g.name.values, "g_km2": rank_g.g_apt_km2.values})
    (out_dir / "ranking_area_apta.tex").write_text(
        to_tex(r, "rlrlr", ["\\#", "Microsoft", "km$^2$", "Google", "km$^2$"]), encoding="utf-8")
    r.to_csv(out_dir / "ranking_area_apta.csv", index=False)
    s = summary
    md = ["# Comparación Microsoft vs Google", "",
          f"{s['municipios_comparables']} de {s['municipios']} municipios comparables; sin datos de Google: "
          f"{', '.join(s['municipios_sin_datos_google']) or 'ninguno'}.", "",
          "| Fuente | Edificios | Área total (km²) | Techos aptos | Área apta (km²) |", "|---|---:|---:|---:|---:|"]
    md += [f"| {k} | {s[k]['edificios']:,} | {s[k]['area_total_km2']:,} | {s[k]['techos_aptos']:,} | "
           f"{s[k]['area_apta_km2']:,} |" for k in ("microsoft", "google")]
    if "correlacion" in s:
        md += ["", "Correlación por municipio: " + ", ".join(f"{k} {v}" for k, v in s["correlacion"].items()),
               "Razón Google/Microsoft: " + ", ".join(f"{k} {v}" for k, v in s["razon_google_microsoft"].items()),
               f"Concordancia del ranking por área apta: {s['concordancia_ranking']['interseccion_top_k']} de "
               f"{s['concordancia_ranking']['k']} municipios comunes en el top (Spearman de rangos "
               f"{s['concordancia_ranking']['spearman_rangos']})."]
    md += ["", "## Mayores discrepancias en área apta (absolutas)", "", absolute.round(3).to_markdown(index=False)
           if hasattr(absolute, "to_markdown") and _has_tabulate() else absolute.round(3).to_string(index=False)]
    (out_dir / "comparacion.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def _has_tabulate():
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    a = ap.parse_args()
    cfg = load_config()
    path = Path(a.input) if a.input else ROOT / cfg["input_csv"]
    if not path.exists():
        path = ROOT / cfg["fallback_csv"]
        print(f"Aviso: no existe {cfg['input_csv']}; se usa {cfg['fallback_csv']} (EDA de la Entrega 3)")
    c = compare(read_results(path))
    summary = summarize(c, cfg)
    absolute, relative = top_discrepancies(c, cfg)
    rank_ms, rank_g = ranking(c, cfg)
    write_outputs(ROOT / cfg["out_dir"], c, summary, absolute, relative, rank_ms, rank_g, by_subregion(c))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nEscrito en {cfg['out_dir']}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
