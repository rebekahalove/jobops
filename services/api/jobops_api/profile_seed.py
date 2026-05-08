from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_public_seed_profile() -> dict[str, Any]:
    profile_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "profile"
        / "data"
        / "rebekah-love.public.seed.json"
    )
    return json.loads(profile_path.read_text(encoding="utf-8"))
