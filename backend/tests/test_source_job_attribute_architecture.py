from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[1]

AUTHORITATIVE_SOURCE_WRITERS = {
    (
        "app/services/offertoday_detail_pipeline.py",
        "_persist_success",
        "project",
    ),
    (
        "app/services/offertoday_job_repair_service.py",
        "_persist_canonical_job",
        "project",
    ),
    (
        "app/workers/run_ingest_worker.py",
        "_persist_event",
        "project_source_attributes",
    ),
    (
        "scripts/ctgoodjobs_standalone_crawl.py",
        "_persist_ctgoodjobs_job",
        "project_source_attributes",
    ),
    (
        "scripts/jobsdb_standalone_crawl.py",
        "run_detail_phase",
        "project_source_attributes",
    ),
}

DIRECT_JOB_CONSTRUCTORS = {
    ("app/api/jobs.py", "create_manual_job"),
    ("app/repositories/job_repository.py", "_create_source_job"),
}


def _function(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError(f"{path.name} does not define {name}")


def _attribute_call_lines(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    attribute: str,
) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    )


def _source_files() -> list[Path]:
    return sorted((BACKEND_ROOT / "app").rglob("*.py")) + sorted(
        (BACKEND_ROOT / "scripts").glob("*.py")
    )


def test_standalone_source_writers_project_between_job_upsert_and_commit():
    writers = (
        (
            BACKEND_ROOT / "scripts" / "jobsdb_standalone_crawl.py",
            "run_detail_phase",
        ),
        (
            BACKEND_ROOT / "scripts" / "ctgoodjobs_standalone_crawl.py",
            "_persist_ctgoodjobs_job",
        ),
    )

    for path, function_name in writers:
        function = _function(path, function_name)
        upsert_lines = _attribute_call_lines(function, "upsert_source_job")
        projection_lines = _attribute_call_lines(
            function,
            "project_source_attributes",
        )
        commit_lines = _attribute_call_lines(function, "commit")

        assert len(upsert_lines) == 1, path
        assert len(projection_lines) == 1, path
        assert len(commit_lines) == 1, path
        assert upsert_lines[0] < projection_lines[0] < commit_lines[0], path


def test_offertoday_repair_projects_in_the_same_unit_of_work_as_job_upsert():
    path = BACKEND_ROOT / "app" / "services" / "offertoday_job_repair_service.py"
    function = _function(path, "_persist_canonical_job")

    upsert_lines = _attribute_call_lines(function, "upsert_source_job")
    projection_lines = _attribute_call_lines(function, "project")

    assert len(upsert_lines) == 1
    assert len(projection_lines) == 1
    assert upsert_lines[0] < projection_lines[0]


def test_authoritative_source_writer_inventory_requires_module_projection():
    actual_writers: set[tuple[str, str, str]] = set()
    for path in _source_files():
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _attribute_call_lines(function, "upsert_source_job"):
                continue
            projection_methods = [
                method
                for method in ("project", "project_source_attributes")
                if _attribute_call_lines(function, method)
            ]
            relative_path = str(path.relative_to(BACKEND_ROOT))
            assert projection_methods, (
                f"{relative_path}:{function.name} writes a collected Job "
                "without Source Job Attribute projection"
            )
            assert len(projection_methods) == 1, (
                relative_path,
                function.name,
                projection_methods,
            )
            actual_writers.add((relative_path, function.name, projection_methods[0]))

    assert actual_writers == AUTHORITATIVE_SOURCE_WRITERS


def test_direct_job_constructor_inventory_has_no_collected_writer_bypass():
    actual_constructors: set[tuple[str, str]] = set()
    for path in _source_files():
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            constructs_job = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Job"
                for node in ast.walk(function)
            )
            if constructs_job:
                actual_constructors.add(
                    (str(path.relative_to(BACKEND_ROOT)), function.name)
                )

    assert actual_constructors == DIRECT_JOB_CONSTRUCTORS


def test_automated_source_attribute_modules_cannot_reach_human_decision_interfaces():
    forbidden_names = {
        "DecisionCommand",
        "DecisionTransition",
        "GovernanceUnitOfWork",
    }
    scoped_paths = sorted(
        (BACKEND_ROOT / "app" / "job_intelligence" / "source_attributes").glob("*.py")
    ) + [
        BACKEND_ROOT / relative_path
        for relative_path, _function_name, _projection in sorted(
            AUTHORITATIVE_SOURCE_WRITERS
        )
    ]

    for path in scoped_paths:
        tree = ast.parse(path.read_text())
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert referenced_names.isdisjoint(forbidden_names), path
