"""Explicit, safe provider selection for CBS adapters."""

from __future__ import annotations

from collections.abc import Callable

from sentinel.adapters.cbs.placeholder import PlaceholderCBSAdapter
from sentinel.adapters.cbs.port import CBSAdapter
from sentinel.adapters.cbs.simulator import SimulatorCBSAdapter

_ALLOWED_PROVIDERS: dict[str, Callable[..., CBSAdapter]] = {
    "simulation": SimulatorCBSAdapter,
    "placeholder": PlaceholderCBSAdapter,
}


class UnsupportedCBSProviderError(ValueError):
    """Raised when a CBS provider is not explicitly supported."""


def register_cbs_adapter(provider: str, factory: Callable[..., CBSAdapter]) -> None:
    """Register an explicitly implemented provider.

    Future bank adapters must be added here only after they are implemented and
    approved; endpoint configuration alone is never enough to cause a connection.
    """
    normalized = (provider or "").strip().lower()
    if not normalized:
        raise ValueError("provider must not be empty")
    _ALLOWED_PROVIDERS[normalized] = factory


def create_cbs_adapter(
    provider: str,
    *,
    environment: str | None = None,
    endpoint: str | None = None,
) -> CBSAdapter:
    """Construct an explicit adapter implementation or fail safely."""
    normalized = (provider or "").strip().lower()
    if normalized not in _ALLOWED_PROVIDERS:
        raise UnsupportedCBSProviderError(
            "unsupported CBS provider; only simulation and placeholder are enabled by default"
        )
    if endpoint:
        raise ValueError(
            "explicit CBS endpoint configuration is rejected for simulation/placeholder providers; "
            "real bank connectivity requires an explicitly implemented and approved adapter"
        )
    factory = _ALLOWED_PROVIDERS[normalized]
    if normalized == "simulation":
        return factory(environment=environment or "simulation")
    if normalized == "placeholder":
        return factory(environment=environment or "development")
    return factory()


def supported_cbs_providers() -> tuple[str, ...]:
    """Return the set of explicitly supported provider keys."""
    return tuple(sorted(_ALLOWED_PROVIDERS))
