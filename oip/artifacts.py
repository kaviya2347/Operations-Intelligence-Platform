"""Read/write analytics artifacts (JSON) consumed by the API and the static build."""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from oip import config


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _clean(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    return o


def save(name: str, obj) -> None:
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.ARTIFACTS_DIR / f"{name}.json").write_text(json.dumps(_clean(obj), default=_default, separators=(",", ":")))


def load(name: str, default=None):
    p = config.ARTIFACTS_DIR / f"{name}.json"
    if not p.exists():
        return default
    return json.loads(p.read_text())


def dumps(obj) -> str:
    return json.dumps(_clean(obj), default=_default, separators=(",", ":"))
