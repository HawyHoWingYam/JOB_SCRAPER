"""Service package exports with lazy imports to avoid import-time side effects."""

__all__: list[str] = []


def __getattr__(name):
    raise AttributeError(f"module 'app.services' has no attribute {name!r}")
