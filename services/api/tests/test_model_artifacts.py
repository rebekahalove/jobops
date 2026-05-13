from __future__ import annotations

import json

from jobops_api.model_artifacts import create_artifact_run


def test_artifact_run_disabled_writes_nothing(tmp_path) -> None:
    artifact_run = create_artifact_run(
        artifact_subdirectory="profile-intake",
        enabled=False,
        repo_root=tmp_path,
        save_raw_text=False,
    )

    artifact_run.write_json("metadata.json", {"ok": True})
    artifact_run.write_raw_text("prompt.txt", "raw")

    assert not (tmp_path / "artifacts").exists()


def test_artifact_run_writes_json_and_gates_raw_text(tmp_path) -> None:
    artifact_run = create_artifact_run(
        artifact_subdirectory="profile-intake",
        enabled=True,
        repo_root=tmp_path,
        run_id="run/with spaces",
        save_raw_text=False,
    )

    artifact_run.write_json("metadata.json", {"ok": True})
    artifact_run.write_raw_text("prompt.txt", "raw")

    assert artifact_run.run_id == "run_with_spaces"
    assert artifact_run.artifact_path and artifact_run.artifact_path.startswith("artifacts")
    assert artifact_run.run_dir is not None
    assert json.loads((artifact_run.run_dir / "metadata.json").read_text(encoding="utf-8")) == {"ok": True}
    assert not (artifact_run.run_dir / "prompt.txt").exists()


def test_artifact_run_writes_raw_text_when_enabled(tmp_path) -> None:
    artifact_run = create_artifact_run(
        artifact_subdirectory="../profile intake",
        enabled=True,
        repo_root=tmp_path,
        save_raw_text=True,
    )

    artifact_run.write_raw_text("raw response.txt", "raw")

    assert artifact_run.run_dir is not None
    assert (artifact_run.run_dir / "raw_response.txt").read_text(encoding="utf-8") == "raw"
    assert artifact_run.run_dir.is_relative_to(tmp_path / "artifacts")
