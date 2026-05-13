from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ArtifactRun:
    enabled: bool
    save_raw_text: bool
    run_id: str | None = None
    run_dir: Path | None = None
    artifact_path: str | None = None

    def write_json(self, filename: str, value: object) -> None:
        if not self.enabled or self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / sanitize_filename(filename)).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def write_raw_text(self, filename: str, value: str) -> None:
        if not self.enabled or not self.save_raw_text or self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / sanitize_filename(filename)).write_text(value, encoding="utf-8")


def create_artifact_run(
    *,
    artifact_subdirectory: str,
    enabled: bool,
    repo_root: Path,
    save_raw_text: bool,
    run_id: str | None = None,
) -> ArtifactRun:
    if not enabled:
        return ArtifactRun(enabled=False, save_raw_text=save_raw_text)

    created_at = datetime.now(timezone.utc)
    next_run_id = sanitize_path_segment(run_id or create_run_id())
    safe_subdirectory = Path(*[sanitize_path_segment(part) for part in Path(artifact_subdirectory).parts])
    run_dir = repo_root / "artifacts" / safe_subdirectory / f"{format_timestamp(created_at)}_{next_run_id}"
    artifact_path = str(run_dir.relative_to(repo_root))

    return ArtifactRun(
        artifact_path=artifact_path,
        enabled=True,
        run_dir=run_dir,
        run_id=next_run_id,
        save_raw_text=save_raw_text,
    )


def create_run_id() -> str:
    return uuid4().hex[:8]


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def sanitize_filename(value: str) -> str:
    return sanitize_path_segment(value)


def sanitize_path_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)
