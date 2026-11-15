#!/usr/bin/env python3
"""Análisis exploratorio (EDA) de las huellas de edificios cargadas en MongoDB.

Calcula con agregaciones de MongoDB (sin traer los documentos a Python): conteos y áreas por municipio, distribución
de áreas, distribución de confianza (Google), techos aptos según el criterio parametrizado, y comparación entre
Microsoft y Google. Opcionalmente mide el solapamiento entre fuentes sobre una muestra.

Uso:
    python src/buildings_eda.py
    python src/buildings_eda.py --overlap        # además estima qué porcentaje de edificios de Google tiene uno de Microsoft encima
Salida: docs/eda/ (CSV, PNG, eda_resumen.md y eda_resumen.tex)
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from buildings_cfg import load_config, repo_path  # noqa: E402

AREA_BINS = [0, 10, 15, 25, 50, 100, 200, 500, 1000, 1e12]
CONF_BINS = [0, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0001]


# ------------------------------------------------------------------ consultas (MongoDB)
def per_municipality(col, min_area, min_conf=None):
    apt = {"$cond": [{"$and": [{"$gte": ["$area_m2", min_area]}] +
                      ([{"$gte": ["$confidence", min_conf]}] if min_conf is not None else [])}, 1, 0]}
    pipe = [{"$group": {"_id": "$municipality_code", "n_buildings": {"$sum": 1}, "area_total_m2": {"$sum": "$area_m2"},
                        "area_mean_m2": {"$avg": "$area_m2"}, "n_apt": {"$sum": apt},
                        "area_apt_m2": {"$sum": {"$cond": [apt, "$area_m2", 0]}}}}]
    df = pd.DataFrame(list(col.aggregate(pipe, allowDiskUse=True)))
    return df.rename(columns={"_id": "municipality_code"}) if not df.empty else df


def histogram(col, field, bins):
    pipe = [{"$bucket": {"groupBy": f"${field}", "boundaries": bins, "default": "otros", "output": {"n": {"$sum": 1}}}}]
    rows = list(col.aggregate(pipe, allowDiskUse=True))
    return pd.DataFrame([{"lower": r["_id"], "n": r["n"]} for r in rows if r["_id"] != "otros"])


def overall(col):
    r = list(col.aggregate([{"$group": {"_id": None, "n": {"$sum": 1}, "mean": {"$avg": "$area_m2"},
                                        "std": {"$stdDevPop": "$area_m2"}, "min": {"$min": "$area_m2"},
                                        "max": {"$max": "$area_m2"}, "total": {"$sum": "$area_m2"}}}], allowDiskUse=True))
    out = r[0] if r else {}
    try:                                                      # $percentile existe desde MongoDB 7.0
        p = list(col.aggregate([{"$group": {"_id": None, "p": {"$percentile": {"input": "$area_m2", "p": [0.5, 0.9, 0.99],
                                                                               "method": "approximate"}}}}], allowDiskUse=True))
        out["median"], out["p90"], out["p99"] = p[0]["p"]
    except Exception:  # noqa: BLE001
        pass
    return out


def overlap_sample(db, cfg, n, min_area):
    """% de edificios de Google (muestra) que intersectan al menos uno de Microsoft."""
    g, m = db[cfg["collections"]["google"]], db[cfg["collections"]["microsoft"]]
    docs = list(g.aggregate([{"$match": {"area_m2": {"$gte": min_area}}}, {"$sample": {"size": n}},
                             {"$project": {"geometry": 1}}]))
    hit = sum(1 for d in docs if m.count_documents({"geometry": {"$geoIntersects": {"$geometry": d["geometry"]}}}, limit=1))
    return {"sample": len(docs), "with_microsoft_overlap": hit, "pct": round(100 * hit / len(docs), 1) if docs else None}


# ------------------------------------------------------------------ tablas y figuras (pandas/matplotlib; sin MongoDB)
def combine(ms, gg, names):
    df = ms.add_prefix("ms_").rename(columns={"ms_municipality_code": "municipality_code"}).merge(
        gg.add_prefix("g_").rename(columns={"g_municipality_code": "municipality_code"}), on="municipality_code", how="outer")
    df = df.merge(names, on="municipality_code", how="left").fillna({"ms_n_buildings": 0, "g_n_buildings": 0})
    df["ratio_g_ms"] = df["g_n_buildings"] / df["ms_n_buildings"].where(df["ms_n_buildings"] > 0)
    return df


def summary_table(stats, apt, overlap=None):
    rows = []
    for src in ("microsoft", "google"):
        s, a = stats.get(src, {}), apt.get(src, {})
        rows.append({"Fuente": src, "Edificios": int(s.get("n", 0)), "Área media (m²)": round(s.get("mean", 0), 1),
                     "Mediana (m²)": round(s["median"], 1) if "median" in s else None,
                     "P99 (m²)": round(s["p99"], 1) if "p99" in s else None,
                     "Área total (km²)": round(s.get("total", 0) / 1e6, 2),
                     "Techos aptos": int(a.get("n_apt", 0)), "Área apta (km²)": round(a.get("area_apt_m2", 0) / 1e6, 2)})
    return pd.DataFrame(rows)


def make_figures(out, combined, hist_area, hist_conf):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"microsoft": "#1F4E79", "google": "#C55A11"}
    # 1) distribución de áreas
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    width = 0.38
    for k, (src, h) in enumerate(hist_area.items()):
        if h.empty:
            continue
        pct = 100 * h["n"] / h["n"].sum()
        labels = [f"{int(l)}" for l in h["lower"]]
        ax.bar([i + (k - 0.5) * width for i in range(len(h))], pct, width, label=src, color=colors[src])
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([f"≥{l}" for l in labels], fontsize=8)
    ax.set_xlabel("Área del edificio (m², límite inferior del rango)")
    ax.set_ylabel("% de edificios")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "hist_area.png", dpi=180)
    plt.close(fig)
    # 2) confianza de Google
    if hist_conf is not None and not hist_conf.empty:
        fig, ax = plt.subplots(figsize=(6.5, 3.2))
        ax.bar([f"{l:.2f}" for l in hist_conf["lower"]], 100 * hist_conf["n"] / hist_conf["n"].sum(), color=colors["google"])
        ax.set_xlabel("Confianza (límite inferior del rango)")
        ax.set_ylabel("% de edificios")
        ax.tick_params(axis="x", labelsize=8)
        fig.tight_layout()
        fig.savefig(out / "hist_confianza_google.png", dpi=180)
        plt.close(fig)
    # 3) conteo por municipio: Microsoft vs Google
    d = combined.dropna(subset=["ms_n_buildings", "g_n_buildings"])
    d = d[(d["ms_n_buildings"] > 0) & (d["g_n_buildings"] > 0)]
    if not d.empty:
        fig, ax = plt.subplots(figsize=(4.6, 4.2))
        ax.scatter(d["ms_n_buildings"], d["g_n_buildings"], s=14, color="#1F4E79", alpha=0.8)
        lim = [d[["ms_n_buildings", "g_n_buildings"]].min().min(), d[["ms_n_buildings", "g_n_buildings"]].max().max()]
        ax.plot(lim, lim, "--", color="gray", lw=1)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Edificios Microsoft por municipio")
        ax.set_ylabel("Edificios Google por municipio")
        fig.tight_layout()
        fig.savefig(out / "scatter_municipios.png", dpi=180)
        plt.close(fig)
    # 4) top 15 municipios por área apta
    if "g_area_apt_m2" in combined or "ms_area_apt_m2" in combined:
        top = combined.assign(a=combined[["ms_area_apt_m2", "g_area_apt_m2"]].max(axis=1)).nlargest(15, "a")
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        y = range(len(top))
        ax.barh([i + 0.2 for i in y], top["ms_area_apt_m2"].fillna(0) / 1e6, 0.4, label="microsoft", color=colors["microsoft"])
        ax.barh([i - 0.2 for i in y], top["g_area_apt_m2"].fillna(0) / 1e6, 0.4, label="google", color=colors["google"])
        ax.set_yticks(list(y))
        ax.set_yticklabels(top["name"].fillna(top["municipality_code"]), fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Área de techos aptos (km²)")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "top15_area_apta.png", dpi=180)
        plt.close(fig)


def write_summary(out, table, overlap):
    md = ["# EDA de huellas de edificios\n", table.to_markdown(index=False) if hasattr(table, "to_markdown") else table.to_string(index=False)]
    if overlap:
        md.append(f"\nSolapamiento: {overlap['with_microsoft_overlap']} de {overlap['sample']} edificios de Google "
                  f"({overlap['pct']} %) intersectan al menos uno de Microsoft.")
    (out / "eda_resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    cols = list(table.columns)
    esc = lambda s: str(s).replace("_", r"\_").replace("²", r"\textsuperscript{2}").replace("%", r"\%")  # noqa: E731
    body = "\n".join(" & ".join(esc(v) if i == 0 else f"{v:,}" if isinstance(v, int) else esc(v) for i, v in enumerate(r)) + r" \\"
                     for r in table.itertuples(index=False))
    (out / "eda_resumen.tex").write_text(
        "\\begin{tabular}{l" + "r" * (len(cols) - 1) + "}\n\\toprule\n" + " & ".join(esc(c) for c in cols) + " \\\\\n\\midrule\n"
        + body + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlap", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    out = repo_path(cfg["eda"]["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    from pymongo import MongoClient

    client = MongoClient(cfg["mongo"]["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit("No se pudo conectar a MongoDB (¿docker compose up -d?): " + str(e)[:120])
    db = client[cfg["mongo"]["database"]]
    rs = cfg["roof_suitability"]
    cols = {s: db[cfg["collections"][s]] for s in ("microsoft", "google")}
    names = pd.DataFrame(list(db[cfg["collections"]["municipalities"]].find({}, {"name": 1, "pdet_subregion": 1})))
    names = names.rename(columns={"_id": "municipality_code"})

    stats = {s: overall(c) for s, c in cols.items()}
    pm = {"microsoft": per_municipality(cols["microsoft"], rs["min_area_m2"]),
          "google": per_municipality(cols["google"], rs["min_area_m2"], rs["min_confidence"])}
    combined = combine(pm["microsoft"], pm["google"], names)
    combined.to_csv(out / "por_municipio.csv", index=False)
    hist_area = {s: histogram(c, "area_m2", AREA_BINS) for s, c in cols.items()}
    hist_conf = histogram(cols["google"], "confidence", CONF_BINS)
    hist_area["microsoft"].to_csv(out / "hist_area_microsoft.csv", index=False)
    hist_area["google"].to_csv(out / "hist_area_google.csv", index=False)
    hist_conf.to_csv(out / "hist_confianza_google.csv", index=False)
    apt = {s: {"n_apt": int(pm[s]["n_apt"].sum()), "area_apt_m2": float(pm[s]["area_apt_m2"].sum())} for s in pm}
    overlap = overlap_sample(db, cfg, cfg["evidence"]["overlap_sample"], rs["min_area_m2"]) if a.overlap else None
    table = summary_table(stats, apt)
    make_figures(out, combined, hist_area, hist_conf)
    write_summary(out, table, overlap)
    print(table.to_string(index=False))
    if overlap:
        print(overlap)
    print(f"\nEDA escrito en {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
