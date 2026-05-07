"""Service package exports with lazy imports to avoid import-time side effects."""

__all__ = [
    "get_skill_normalizer",
    "get_job_category_normalizer",
    "get_taxonomy_visibility_service",
]


def __getattr__(name):
    if name == "get_skill_normalizer":
        from app.services.skill_normalizer import get_skill_normalizer

        return get_skill_normalizer
    if name == "get_job_category_normalizer":
        from app.services.job_category_normalizer import get_job_category_normalizer

        return get_job_category_normalizer
    if name == "get_taxonomy_visibility_service":
        from app.services.taxonomy_visibility_service import get_taxonomy_visibility_service

        return get_taxonomy_visibility_service
    raise AttributeError(f"module 'app.services' has no attribute {name!r}")
