#!/usr/bin/env python3
"""Read-only audit of historical polluted skills under Other / General."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal  # noqa: E402
from app.services.skill_normalizer import (  # noqa: E402
    SkillNormalizer,
    normalize_exact_skill_key,
)


def _data_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "app" / "data" / filename


def normalize_lookup_key(value: str) -> str:
    text_value = str(value or "").strip()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text_value = text_value.replace(dash, "-")
    text_value = re.sub(r"\s+", " ", text_value).lower().strip()
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def _looks_phrase_like(value: str) -> bool:
    return len(normalize_lookup_key(value).split()) >= 4


def load_backfill_curations(path: str | Path | None = None) -> dict[str, Any]:
    curation_path = (
        Path(path) if path is not None else _data_path("skill_backfill_curations.json")
    )
    payload = json.loads(curation_path.read_text())
    entries = payload.get("entries") or {}
    normalized_entries: dict[str, dict[str, Any]] = {}

    for raw_key, config in entries.items():
        action = str((config or {}).get("action") or "").strip()
        if action not in {"merge", "generic", "review"}:
            raise ValueError(f"Unsupported curation action for '{raw_key}': {action}")
        normalized_entries[normalize_exact_skill_key(raw_key)] = dict(config)

    return {
        "path": str(curation_path),
        "minimum_distinct_jobs": int(payload.get("minimum_distinct_jobs") or 100),
        "entries": normalized_entries,
    }


def _resolved_threshold(
    curations: dict[str, Any], min_distinct_jobs: int | None
) -> int:
    if min_distinct_jobs is not None:
        return int(min_distinct_jobs)
    return int(curations["minimum_distinct_jobs"])


def _polluted_skill_rows_query(
    *, min_distinct_jobs: int | None = None, exact_distinct_jobs: int | None = None
) -> str:
    having_clauses = []
    if min_distinct_jobs is not None:
        having_clauses.append("COUNT(DISTINCT js.job_id) >= :min_distinct_jobs")
    if exact_distinct_jobs is not None:
        having_clauses.append("COUNT(DISTINCT js.job_id) = :exact_distinct_jobs")
    having_sql = ""
    if having_clauses:
        having_sql = "\n            HAVING " + " AND ".join(having_clauses)

    return f"""
            SELECT
                s.id AS skill_id,
                s.name AS skill_name,
                sc.name AS category_name,
                st.name AS technology_name,
                COUNT(js.job_id) AS job_links,
                COUNT(DISTINCT js.job_id) AS distinct_jobs
            FROM skills s
            JOIN skill_technologies st ON st.id = s.technology_id
            JOIN skill_categories sc ON sc.id = st.category_id
            LEFT JOIN job_skills js ON js.skill_id = s.id
            WHERE lower(sc.name) = 'other'
              AND lower(st.name) = 'general'
            GROUP BY s.id, s.name, sc.name, st.name{having_sql}
            ORDER BY COUNT(DISTINCT js.job_id) DESC, COUNT(js.job_id) DESC, s.name ASC
            """


def _query_polluted_skill_rows(
    db: Session,
    *,
    min_distinct_jobs: int | None = None,
    exact_distinct_jobs: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, int] = {}
    if min_distinct_jobs is not None:
        params["min_distinct_jobs"] = min_distinct_jobs
    if exact_distinct_jobs is not None:
        params["exact_distinct_jobs"] = exact_distinct_jobs

    result = db.execute(
        text(
            _polluted_skill_rows_query(
                min_distinct_jobs=min_distinct_jobs,
                exact_distinct_jobs=exact_distinct_jobs,
            )
        ),
        params,
    )
    return [dict(row) for row in result.mappings()]


def _raw_polluted_skill_rows(
    db: Session, *, min_distinct_jobs: int
) -> list[dict[str, Any]]:
    rows = _query_polluted_skill_rows(db, min_distinct_jobs=min_distinct_jobs)

    if min_distinct_jobs > 1:
        seen_skill_ids = {str(row["skill_id"]) for row in rows}
        for row in _query_polluted_skill_rows(db, exact_distinct_jobs=1):
            if str(row["skill_id"]) in seen_skill_ids:
                continue
            if not _looks_phrase_like(str(row["skill_name"] or "")):
                continue
            rows.append(row)

    rows.sort(
        key=lambda row: (
            -int(row["distinct_jobs"] or 0),
            -int(row["job_links"] or 0),
            str(row["skill_name"] or ""),
        )
    )
    return rows


def _classify_skill_row(
    row: dict[str, Any],
    curations: dict[str, Any],
    normalizer: SkillNormalizer,
) -> dict[str, Any]:
    source_name = row["skill_name"]
    normalized_name = normalize_exact_skill_key(source_name)
    curation = dict(curations["entries"].get(normalized_name) or {})

    if (
        not curation
        and int(row["distinct_jobs"] or 0) <= 1
        and _looks_phrase_like(source_name)
    ):
        curation = {"action": "review", "note": "Phrase-like one-off skill mention"}

    if not curation:
        decision = normalizer.resolve_extracted_skill(
            {
                "name": source_name,
                "kind": "technical",
                "resolution": "unresolved",
            }
        )
        action = str(decision.get("action") or "review").strip()
        if action == "match_existing":
            hierarchy = normalizer.get_skill_hierarchy(decision["skill_id"])
            curation = {
                "action": "merge",
                "target": {
                    "category": hierarchy["category"],
                    "technology": hierarchy["technology"],
                    "skill": hierarchy["skill"],
                },
            }
        elif action == "generic_tag":
            curation = {
                "action": "generic",
                "generic_tag": str(decision.get("generic_tag") or source_name).strip(),
            }
        elif action == "reject":
            curation = {
                "action": "generic",
                "generic_tag": source_name,
                "note": str(decision.get("reason") or "suppressed technical term"),
            }

    action = str(curation.get("action") or "review").strip()

    entry: dict[str, Any] = {
        "action": action,
        "source_skill": {
            "id": str(row["skill_id"]),
            "name": source_name,
            "normalized_name": normalized_name,
            "category": row["category_name"],
            "technology": row["technology_name"],
            "job_links": int(row["job_links"] or 0),
            "distinct_jobs": int(row["distinct_jobs"] or 0),
        },
    }

    if action == "merge":
        entry["target"] = dict(curation.get("target") or {})
    elif action == "generic":
        entry["generic_tag"] = str(curation.get("generic_tag") or source_name).strip()
    elif action == "review" and curation.get("note"):
        entry["note"] = str(curation["note"])

    return entry


def audit_skill_history(
    db: Session,
    *,
    min_distinct_jobs: int | None = None,
    curation_path: str | Path | None = None,
    only_curated: bool = False,
) -> dict[str, Any]:
    curations = load_backfill_curations(curation_path)
    threshold = _resolved_threshold(curations, min_distinct_jobs)
    normalizer = SkillNormalizer(db)
    entries = []
    for row in _raw_polluted_skill_rows(db, min_distinct_jobs=threshold):
        entry = _classify_skill_row(row, curations, normalizer)
        if (
            only_curated
            and entry["source_skill"]["normalized_name"] not in curations["entries"]
        ):
            continue
        entries.append(entry)

    summary = {
        "merge": {
            "skill_count": 0,
            "affected_distinct_jobs": 0,
            "affected_job_links": 0,
        },
        "generic": {
            "skill_count": 0,
            "affected_distinct_jobs": 0,
            "affected_job_links": 0,
        },
        "review": {
            "skill_count": 0,
            "affected_distinct_jobs": 0,
            "affected_job_links": 0,
        },
    }

    for entry in entries:
        bucket = summary[entry["action"]]
        bucket["skill_count"] += 1
        bucket["affected_distinct_jobs"] += entry["source_skill"]["distinct_jobs"]
        bucket["affected_job_links"] += entry["source_skill"]["job_links"]

    return {
        "minimum_distinct_jobs": threshold,
        "curation_path": curations["path"],
        "only_curated": only_curated,
        "entries": entries,
        "summary": summary,
    }


def _write_report_if_requested(report: dict[str, Any], output_path: str | None) -> None:
    if not output_path:
        return
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, default=str))


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "minimum_distinct_jobs": report.get("minimum_distinct_jobs"),
        "curation_path": report.get("curation_path"),
        "only_curated": report.get("only_curated"),
        "summary": report.get("summary"),
        "dry_run": report.get("dry_run"),
        "processed": report.get("processed"),
        "entry_count": len(report.get("entries") or []),
    }
    return {key: value for key, value in summary.items() if value is not None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Read-only polluted skill audit")
    audit_parser.add_argument("--min-distinct-jobs", type=int, default=None)
    audit_parser.add_argument("--curation-path", type=str, default=None)
    audit_parser.add_argument("--output", type=str, default=None)
    audit_parser.add_argument(
        "--only-curated",
        action="store_true",
        help="Limit the audit to explicitly curated polluted skills",
    )
    audit_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Retired mutation path; always fails closed",
    )
    apply_parser.add_argument("--min-distinct-jobs", type=int, default=None)
    apply_parser.add_argument("--curation-path", type=str, default=None)
    apply_parser.add_argument("--output", type=str, default=None)
    apply_parser.add_argument(
        "--only-curated",
        action="store_true",
        help="Apply only explicitly curated polluted skills",
    )
    apply_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true", help="Persist historical cleanup"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="Simulate without committing"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "apply":
        parser.error(
            "legacy Skill history mutation is retired; use the governed "
            "Skill Candidate decision API or the read-only audit command"
        )

    db = SessionLocal()
    try:
        report = audit_skill_history(
            db,
            min_distinct_jobs=args.min_distinct_jobs,
            curation_path=args.curation_path,
            only_curated=bool(args.only_curated),
        )
        _write_report_if_requested(report, getattr(args, "output", None))
        payload = _summarize_report(report) if bool(args.summary_only) else report
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
