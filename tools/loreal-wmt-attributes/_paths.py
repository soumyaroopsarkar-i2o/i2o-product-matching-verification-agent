from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "loreal-wmt-attributes"
LEGACY_DATA_DIR = REPO_ROOT / "loreal_wmt_attributes" / "loreal_wmt_attributes"


def resolve_data_dir() -> Path:
    configured = os.environ.get("LOREAL_WMT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if DEFAULT_DATA_DIR.exists():
        return DEFAULT_DATA_DIR
    return LEGACY_DATA_DIR


DATA_DIR = resolve_data_dir()
