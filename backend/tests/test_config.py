from app.config import Settings


def test_default_cors_origins_cover_docker_and_host_frontend_ports(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    settings = Settings(_env_file=None)
    origins = set(settings.cors_origins.split(","))

    assert origins == {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    }
