"""Service package exports with lazy imports to avoid import-time side effects."""

__all__ = [
    "get_taxonomy_visibility_service",
]


def __getattr__(name):
    if name == "get_taxonomy_visibility_service":
        from app.services.taxonomy_visibility_service import (
            get_taxonomy_visibility_service,
        )

        return get_taxonomy_visibility_service
    raise AttributeError(f"module 'app.services' has no attribute {name!r}")
