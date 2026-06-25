from pathlib import Path


def test_headed_host_requirements_include_pgvector():
    requirements = (
        Path(__file__).resolve().parents[1] / "requirements-headed-host.txt"
    ).read_text(encoding="utf-8")

    assert "pgvector" in requirements
