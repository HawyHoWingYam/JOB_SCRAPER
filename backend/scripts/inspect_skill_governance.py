#!/usr/bin/env python3
"""Read-only governed Skill extraction and rebuild inspection."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from uuid import UUID


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.skill_governance import (  # noqa: E402
    SkillGovernanceRebuildInspector,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "human"), default="json")
    parser.add_argument(
        "--job-id",
        action="append",
        type=UUID,
        default=None,
        help="Restrict inspection to one Job UUID; repeatable",
    )
    return parser


def render_human_report(payload: Mapping[str, object]) -> str:
    def encoded(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    return "\n".join(
        (
            "Skill governance rebuild inspection (read-only)",
            f"active_revision_id: {payload['active_revision_id']}",
            f"jobs_inspected: {payload['jobs_inspected']}",
            f"terms_inspected: {payload['terms_inspected']}",
            f"outcomes: {encoded(payload['outcomes'])}",
            f"affected_jobs: {payload['affected_jobs']}",
            f"no_preserved_evidence_jobs: {payload['no_preserved_evidence_jobs']}",
            f"normalized_collisions: {payload['normalized_collisions']}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        payload = SkillGovernanceRebuildInspector(db).inspect(args.job_id).to_payload()
        if args.format == "human":
            print(render_human_report(payload))
        else:
            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
