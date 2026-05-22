from pathlib import Path
import sys
import tempfile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_audit_docs import validate_audit_docs


def test_validate_audit_docs_accepts_current_tree():
    assert validate_audit_docs(Path("docs/audit")) == []


def test_validate_audit_docs_reports_missing_required_section():
    with tempfile.TemporaryDirectory(dir=BACKEND_ROOT) as tmp_dir:
        audit_root = Path(tmp_dir) / "audit"
        leaf = audit_root / "01-business-domains" / "broken.md"
        leaf.parent.mkdir(parents=True)
        (audit_root / "README.md").write_text(
            "[Broken](01-business-domains/broken.md)\n",
            encoding="utf-8",
        )
        leaf.write_text("## Current Responsibilities\n", encoding="utf-8")

        errors = validate_audit_docs(audit_root)

        assert any(
            "missing required section: Optimization Backlog" in error for error in errors
        )


def test_scheduler_worker_compose_service_has_explicit_command():
    compose_text = (BACKEND_ROOT.parent / "docker-compose.yml").read_text(encoding="utf-8")

    assert "scheduler-worker:" in compose_text
    assert "command: python -m app.workers.run_scheduler_worker" in compose_text
