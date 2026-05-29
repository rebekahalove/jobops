from __future__ import annotations

from ...settings import Settings
from .base import JobSearchRequest, ProviderDiagnostic, ProviderSearchOutcome, ProviderType


class AshbyJobDiscoveryProvider:
    provider_name = "ashby"
    provider_type: ProviderType = "ats_board"

    def is_configured(self, settings: Settings) -> bool:
        return False

    def search(self, request: JobSearchRequest, settings: Settings) -> ProviderSearchOutcome:
        return ProviderSearchOutcome(
            results=[],
            diagnostics=[
                ProviderDiagnostic(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    configured=False,
                    attempted=False,
                    error="Ashby job discovery provider is not implemented yet.",
                )
            ],
            errors=["Ashby job discovery provider is not implemented yet."],
        )

