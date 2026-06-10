from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config) -> None:
    if config.option.basetemp:
        return

    temp_root = Path(config.rootpath) / ".pytest-system-temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(temp_root))
