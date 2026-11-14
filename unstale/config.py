"""Settings, read from the environment with local-dev defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"


def _env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


_INFRA = _env_file(ROOT / "infra" / ".env")
_LOCAL = _env_file(ROOT / ".env")


def setting(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _LOCAL.get(name) or _INFRA.get(name) or default


def dataset_path() -> Path:
    """The dataset the API serves and ingest loads: Northwind unless UNSTALE_DATASET points elsewhere."""
    p = Path(setting("UNSTALE_DATASET", str(DATA / "northwind.json")))
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    hydra_uri: str
    hydra_token: str | None
    namespace: str
    groq_key: str | None
    groq_model: str
    weak_exposure: bool
    store: str = "hydradb"
    kuzu_path: str = "/tmp/unstale.kuzu"

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            hydra_uri=setting("UNSTALE_HYDRA_URI", "bolt://127.0.0.1:17687"),
            hydra_token=setting("UNSTALE_HYDRA_TOKEN") or setting("HYDRA_TOKEN"),
            namespace=setting("UNSTALE_NAMESPACE", "northwind"),
            groq_key=setting("GROQ_API_KEY"),
            groq_model=setting("UNSTALE_LLM_MODEL", "openai/gpt-oss-120b"),
            weak_exposure=(setting("UNSTALE_WEAK_EXPOSURE", "1") != "0"),
            store=setting("UNSTALE_STORE", "hydradb"),
            kuzu_path=setting("UNSTALE_KUZU_PATH", "/tmp/unstale.kuzu"),
        )
