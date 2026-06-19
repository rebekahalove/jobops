from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompanySyncRequest:
    sync_key: str
    provider_name: str = "theirstack"
    provider_type: str = "company_source"
    sync_kind: str = "company_search"
    company_sync_signature_id: str | None = None
    query_text: str | None = None
    query_kind: str | None = None
    criteria_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanySyncResult:
    request: CompanySyncRequest
    status: str = "completed"
    raw_result_count: int = 0
    normalized_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    failed_normalization_count: int = 0
    error: str | None = None
    diagnostics_json: dict[str, Any] = field(default_factory=dict)
    company_ids: tuple[str, ...] = ()
    company_source_ids: tuple[str, ...] = ()
