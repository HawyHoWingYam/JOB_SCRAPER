from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[1]


def _source(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


def test_authoritative_consumers_do_not_import_legacy_skill_authority():
    authoritative_consumers = (
        "app/services/ai_enrichment_service.py",
        "app/services/embedding_document_builder.py",
        "app/services/job_recommendation_service.py",
        "app/workers/run_embedding_worker.py",
        "app/api/job_search_query.py",
        "app/api/jobs.py",
        "app/api/stats.py",
        "app/api/filters.py",
        "app/api/ai.py",
        "app/services/enrichment_run_service.py",
        "scripts/batch_enrich_jobs.py",
    )
    forbidden = {
        "JobSkill",
        "JobSkillMention",
        "SkillNormalizer",
        "SkillReviewCandidate",
        "JobSkillMentionRepository",
        "JobSkillRepository",
    }

    for relative_path in authoritative_consumers:
        tree = ast.parse(_source(relative_path), filename=relative_path)
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert not forbidden & referenced_names, relative_path


def test_background_workers_cannot_reach_human_skill_decision_interfaces():
    worker_paths = tuple(
        path
        for path in (BACKEND_ROOT / "app" / "workers").glob("*.py")
        if path.is_file()
    )
    forbidden = {
        "DecisionCommand",
        "GovernanceUnitOfWork",
        "SkillCandidateDecisionAdapter",
        "SkillCandidateDecisionError",
    }
    for path in worker_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not forbidden & names, path.name


def test_only_skill_governance_module_constructs_authoritative_skill_rows():
    allowed_directory = BACKEND_ROOT / "app" / "job_intelligence" / "skill_governance"
    constructors = {
        "GovernedSkill",
        "GovernedSkillAlias",
        "GovernedJobSkillMention",
        "GovernedJobSkill",
        "SkillCandidate",
    }
    violations: list[str] = []
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        if allowed_directory in path.parents or path.name == "skill_governance.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in constructors
            ):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
    assert violations == []


def test_ai_enrichment_projects_governed_skills_before_its_single_commit():
    source = _source("app/services/ai_enrichment_service.py")
    tree = ast.parse(source)
    enrich = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AIEnrichmentService"
    )
    method = next(
        node
        for node in enrich.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "enrich_job"
    )
    calls = [
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
    ]
    extract_line = min(
        line for line, name in calls if name == "SkillGovernance(db).extract"
    )
    successful_commit_lines = [
        line for line, name in calls if name == "db.commit" and line > extract_line
    ]
    assert successful_commit_lines
    assert extract_line < min(successful_commit_lines)


def test_legacy_skill_governance_scripts_are_read_only_and_fail_closed():
    script_paths = (
        "scripts/govern_skill_history.py",
        "scripts/govern_skill_review_candidates.py",
    )
    forbidden_names = {
        "JobSkill",
        "JobSkillMention",
        "JobSkillMentionRepository",
        "JobSkillRepository",
    }
    forbidden_db_methods = {"commit", "delete", "flush", "rollback", "update"}

    for relative_path in script_paths:
        source = _source(relative_path)
        tree = ast.parse(source, filename=relative_path)
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        mutation_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_db_methods
        }

        assert not forbidden_names & referenced_names, relative_path
        assert mutation_calls == set(), relative_path
        assert "parser.error(" in source, relative_path
        assert "mutation is retired" in source, relative_path


def test_legacy_skill_normalizer_has_no_db_bound_singleton_or_candidate_writer():
    normalizer_source = _source("app/services/skill_normalizer.py")
    service_exports = _source("app/services/__init__.py")

    assert "get_skill_normalizer" not in normalizer_source
    assert "_normalizer_instance" not in normalizer_source
    assert "register_review_candidate" not in normalizer_source
    assert "get_skill_normalizer" not in service_exports
