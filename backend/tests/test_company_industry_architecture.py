from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[1]


def _referenced_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


def test_company_industry_workers_cannot_reach_human_decision_interfaces():
    forbidden = {
        "CompanyIndustryDecisionAdapter",
        "CompanyIndustryDecisionError",
        "DecisionCommand",
        "DecisionTransition",
        "GovernanceUnitOfWork",
    }
    scoped_paths = [
        BACKEND_ROOT / "app" / "job_intelligence" / "company_industry" / "adapters.py",
        BACKEND_ROOT / "app" / "workers" / "run_ingest_worker.py",
        BACKEND_ROOT / "app" / "services" / "offertoday_detail_pipeline.py",
        BACKEND_ROOT / "app" / "services" / "offertoday_job_repair_service.py",
        BACKEND_ROOT / "scripts" / "jobsdb_standalone_crawl.py",
        BACKEND_ROOT / "scripts" / "ctgoodjobs_standalone_crawl.py",
    ]

    for path in scoped_paths:
        assert _referenced_names(path).isdisjoint(forbidden), path


def test_company_industry_assignment_constructor_is_owned_by_the_module():
    constructors: set[tuple[str, str]] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CompanyIndustryAssignment"
                for node in ast.walk(function)
            ):
                constructors.add((str(path.relative_to(BACKEND_ROOT)), function.name))

    assert constructors == {
        (
            "app/job_intelligence/company_industry/read_model.py",
            "_create_assignment",
        )
    }
