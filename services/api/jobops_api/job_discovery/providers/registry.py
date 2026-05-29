from __future__ import annotations

from .adzuna import AdzunaJobDiscoveryProvider
from .ashby import AshbyJobDiscoveryProvider
from .base import JobDiscoveryProvider, JobProviderConfigurationError
from .greenhouse import GreenhouseJobDiscoveryProvider
from .mock import MockJobDiscoveryProvider


def resolve_job_discovery_providers(provider_names: tuple[str, ...]) -> list[JobDiscoveryProvider]:
    providers: list[JobDiscoveryProvider] = []
    for name in provider_names:
        if name == "mock":
            providers.append(MockJobDiscoveryProvider())
        elif name == "adzuna":
            providers.append(AdzunaJobDiscoveryProvider())
        elif name == "greenhouse":
            providers.append(GreenhouseJobDiscoveryProvider())
        elif name == "ashby":
            providers.append(AshbyJobDiscoveryProvider())
        else:
            raise JobProviderConfigurationError(f"Unknown job discovery provider: {name}")
    return providers

