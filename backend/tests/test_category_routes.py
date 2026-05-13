import sys
from pathlib import Path

from fastapi import FastAPI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.category_routes import router as category_router


def test_category_router_no_longer_exposes_legacy_scrape_routes():
    app = FastAPI()
    app.include_router(category_router, prefix="/api")

    route_paths = {route.path for route in app.routes}

    assert "/api/v1/categories/{classification_id}/scrape" not in route_paths
    assert "/api/v1/categories/{classification_id}/status" not in route_paths
    assert "/api/v1/categories/scrape/status" not in route_paths
