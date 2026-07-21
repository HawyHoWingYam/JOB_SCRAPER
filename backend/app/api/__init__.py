from typing import Any


def __getattr__(name: str) -> Any:
    if name != "router":
        raise AttributeError(name)

    from app.api.root_router import router

    return router

__all__ = ["router"]
