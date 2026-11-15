"""Configuración compartida de los scripts de evidencia y EDA de edificios (sin MongoDB)."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ("params.yaml", "spatial.yaml", "buildings_load.yaml", "buildings_analysis.yaml")


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_config():
    """Combina params.yaml (Mongo, criterio de techo apto), spatial.yaml (municipalities), buildings_load.yaml
    (nombres de colecciones) y buildings_analysis.yaml (salidas de evidencia y EDA)."""
    cfg = {}
    for f in FILES:
        _merge(cfg, yaml.safe_load((ROOT / "config" / f).read_text(encoding="utf-8")) or {})
    return cfg


def repo_path(p):
    return ROOT / p


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
