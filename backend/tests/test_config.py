import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _service_block(compose_text: str, service_name: str) -> str:
    lines = compose_text.splitlines()
    header = f"  {service_name}:"
    collecting = False
    service_lines = []

    for line in lines:
        if not collecting:
            if line == header:
                collecting = True
            continue

        if line.startswith("  ") and not line.startswith("    "):
            break

        if line.startswith("    "):
            service_lines.append(line)

    assert service_lines, f"Expected compose service '{service_name}' to exist"
    return "\n".join(service_lines) + "\n"


def test_compose_foundation_uses_pgvector_and_profiles_worker_stubs():
    compose_text = _read("docker-compose.yml")
    postgres_block = _service_block(compose_text, "postgres-db")

    assert "image: pgvector/pgvector:pg15" in postgres_block
    assert '- "5433:5432"' in postgres_block
    assert "- pg_data:/var/lib/postgresql/data" in postgres_block
    assert "- ./database/init:/docker-entrypoint-initdb.d" in postgres_block

    for service_name in (
        "scheduler-worker",
        "crawl-worker",
        "ingest-worker",
        "enrichment-worker",
        "embedding-worker",
        "retrieval-api",
        "recommendation-api",
    ):
        service_block = _service_block(compose_text, service_name)
        assert "profiles:" in service_block
        assert "- workers" in service_block
        assert "dockerfile: Dockerfile.worker" in service_block
        assert f"WORKER_NAME: {service_name}" in service_block


def test_backend_requirements_include_eventized_scraper_dependencies():
    requirements_text = _read("backend/requirements.txt")

    assert "pgvector>=0.3.6" in requirements_text
    assert "scrapy>=2.12.0" in requirements_text
    assert "scrapy-playwright>=0.0.41" in requirements_text
    assert "playwright==1.58.0" in requirements_text


def test_worker_container_and_crawler_docs_exist():
    dockerfile_text = _read("backend/Dockerfile.worker")
    crawler_readme = _read("backend/crawler/README.md")

    assert "COPY requirements.txt ." in dockerfile_text
    assert "COPY requirements-dev.txt ." in dockerfile_text
    assert "pip install --no-cache-dir -r requirements-dev.txt" in dockerfile_text
    assert "python -m playwright install chromium" in dockerfile_text
    assert "ENV WORKER_NAME=worker" in dockerfile_text
    assert "CMD [\"python\", \"-c\"," in dockerfile_text
    assert "uvicorn" not in dockerfile_text

    assert "backend/crawler" in crawler_readme
    assert "Scrapy" in crawler_readme
