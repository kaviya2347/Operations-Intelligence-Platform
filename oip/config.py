"""Central configuration: paths, period, business rules.

Every number here is a business rule agreed with the operations and reporting
teams. Changing one changes metric outputs, so each is documented.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("OIP_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"                 # landing zone: source extracts, may contain PII
DB_PATH = DATA_DIR / "oip.db"              # staging + warehouse (SQLite)
ARTIFACTS_DIR = DATA_DIR / "artifacts"     # analytics outputs consumed by the API
VECTOR_DIR = DATA_DIR / "vectorstore"      # RAG index
KB_DIR = ROOT / "oip" / "copilot" / "kb"   # knowledge base documents (SOPs, RCAs, quality)
WEB_DIR = ROOT / "web"
POWERBI_DIR = ROOT / "powerbi"

SEED = 20260601
PERIOD_START = date(2026, 3, 1)
PERIOD_END = date(2026, 5, 31)             # three months, as approved for extraction
INTERVAL_MIN = 30                          # WFM planning interval

# --- Business rules (metric definitions depend on these) -------------------
SHORT_ABANDON_SEC = 5          # abandons at or under this are excluded from SLA and abandon rate
FCR_WINDOW_DAYS = 7            # repeat contact window for first contact resolution
UNCLOSED_SESSION_SEC = 7200    # handle time above this with no logout event = unclosed session
OCCUPANCY_TARGET = 0.85        # used for non real-time (email/back office) staffing
PLANNED_SHRINKAGE = 0.30       # WFM planning assumption
CSAT_TOP_BOX = 4               # scores 4 and 5 count as satisfied


def _env(name: str, default: str | None = None):
    return field(default_factory=lambda: os.environ.get(name, default))


@dataclass(frozen=True)
class LLMSettings:
    """Read at call time (not import time) so a .env loaded later still applies."""
    provider: str = _env("OIP_LLM_PROVIDER", "auto")             # auto | anthropic | ollama | extractive
    anthropic_model: str = _env("OIP_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    anthropic_key: str | None = _env("ANTHROPIC_API_KEY")
    anthropic_base: str = _env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    ollama_model: str = _env("OIP_OLLAMA_MODEL", "llama3.1")
    ollama_base: str = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def load_env_file(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (no dependency). Existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, ARTIFACTS_DIR, VECTOR_DIR):
        d.mkdir(parents=True, exist_ok=True)
