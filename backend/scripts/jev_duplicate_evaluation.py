from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.system_one import NativeSystemOneClient  # noqa: E402
from app.models.jev import (  # noqa: E402
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.services.jev_duplicate_corpus import (  # noqa: E402
    build_duplicate_corpus_artifact,
    verify_duplicate_corpus_artifact,
)
from app.services.jev_duplicate_evaluation import (  # noqa: E402
    load_duplicate_cases,
    score_duplicate_evaluation,
)
from app.services.jev_duplicate_runner import (  # noqa: E402
    DuplicateObservation,
    JevDuplicateRunner,
)
from app.services.jev_runtime_settings_service import (  # noqa: E402
    JevRuntimeSettingsService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Jev duplicate evaluation")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--controlled", type=Path, required=True)
    validate.add_argument("--real-artifact", type=Path)

    plan = commands.add_parser("plan")
    plan.add_argument("--controlled", type=Path, required=True)
    plan.add_argument(
        "--split", choices=("development", "held_out", "all"), default="development"
    )

    export = commands.add_parser("export-real")
    export.add_argument("--database-url", required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--limit", type=int, default=100)
    export.add_argument("--max-pairs", type=int, default=1_000)
    export.add_argument("--artifact-name")

    run = commands.add_parser("run-controlled")
    run.add_argument("--controlled", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--state-db", type=Path, required=True)
    run.add_argument(
        "--split", choices=("development", "held_out", "all"), default="development"
    )
    run.add_argument("--endpoint", default="https://openrouter.ai/api/alpha/decisions")
    run.add_argument("--model", default="typesafe/jev-1.13")
    run.add_argument("--timeout-seconds", type=int, default=30)
    run.add_argument("--confirm-paid-evaluation", action="store_true")

    report = commands.add_parser("report")
    report.add_argument("--observations", type=Path, required=True)
    report.add_argument("--eligible-positive-pairs", type=int, required=True)
    report.add_argument("--candidate-eligible-positive-pairs", type=int)
    report.add_argument("--recalled-positive-pairs", type=int, required=True)
    report.add_argument("--real-reference-language", action="append", default=[])
    report.add_argument("--json-output", type=Path, required=True)
    report.add_argument("--markdown-output", type=Path, required=True)
    return parser


def _select_cases(path: Path, split: str):
    cases = load_duplicate_cases(path)
    return tuple(case for case in cases if split == "all" or case.split == split)


def _state_session(args, api_key: str):
    args.state_db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{args.state_db}")
    for table in (
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
    ):
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False)()
    JevRuntimeSettingsService(db).update(
        {
            "enabled": True,
            "endpoint": args.endpoint,
            "model": args.model,
            "api_key": api_key,
            "retry_limit": 0,
        }
    )
    db.commit()
    return engine, db


async def _run_controlled(args) -> dict[str, object]:
    if not args.confirm_paid_evaluation:
        raise ValueError("run-controlled requires --confirm-paid-evaluation")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required")
    cases = _select_cases(args.controlled, args.split)
    if not cases:
        raise ValueError("no controlled cases selected")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite observations: {args.output}")
    engine, db = _state_session(args, api_key)
    client = NativeSystemOneClient(
        endpoint=args.endpoint,
        api_key=api_key,
        http_client=httpx.AsyncClient(timeout=args.timeout_seconds),
    )
    try:
        runner = JevDuplicateRunner(db)
        run = runner.start(
            cases=cases,
            manifest_sha256=hashlib.sha256(args.controlled.read_bytes()).hexdigest(),
        )
        db.commit()
        await runner.execute_remaining(run.id, evaluator=client)
        db.commit()
        observations = runner.observations(run.id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(
                json.dumps(asdict(item), ensure_ascii=False, sort_keys=True) + "\n"
                for item in observations
            ),
            encoding="utf-8",
        )
        return {
            "selected": len(cases),
            "observations": len(observations),
            "run_status": runner.runs.get(run.id).status,
        }
    finally:
        await client.aclose()
        db.close()
        engine.dispose()


def _load_observations(path: Path) -> tuple[DuplicateObservation, ...]:
    return tuple(
        DuplicateObservation(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _markdown(report: dict[str, object]) -> str:
    controlled = report["controlled"]
    candidate = report["candidate"]
    execution = report["execution"]
    stability = report["option_reordering_stability"]
    limitations = report["limitations"] or ["None recorded."]
    return "\n".join(
        [
            "# Jev duplicate evaluation report",
            "",
            f"Decision: **{report['decision']}**",
            "",
            "## Frozen metrics",
            "",
            f"- Candidate recall@10: {candidate['recall_at_10']}",
            f"- Answered pair precision: {controlled['precision']}",
            f"- Positive recall: {controlled['recall']}",
            f"- False-association rate: {controlled['false_association_rate']}",
            f"- Actionable coverage: {controlled['actionable_coverage']}",
            f"- Technical failure rate: {controlled['technical_failure_rate']}",
            f"- Option-order stability: {stability['rate']}",
            "",
            "## Execution",
            "",
            f"Tokens: {execution['input_tokens']} input / {execution['output_tokens']} output.",
            f"Provider-reported cost: {execution['provider_reported_microdollars']} microdollars.",
            f"Latency p50/p95: {execution['latency_ms_p50']} / {execution['latency_ms_p95']} ms.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in limitations],
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result: dict[str, object] = {
                "controlled_cases": len(load_duplicate_cases(args.controlled)),
                "valid": True,
            }
            if args.real_artifact:
                verified = verify_duplicate_corpus_artifact(args.real_artifact)
                result["real_jobs"] = verified["manifest"]["job_count"]
                result["real_candidate_pairs"] = verified["manifest"][
                    "candidate_pair_count"
                ]
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "plan":
            selected = len(_select_cases(args.controlled, args.split))
            result = {
                "selected": selected,
                "monetary_authority": "jev_api_console",
                "paid_requests_started": 0,
            }
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "export-real":
            engine = create_engine(args.database_url)
            try:
                artifact = build_duplicate_corpus_artifact(
                    engine,
                    output_dir=args.output_dir,
                    limit=args.limit,
                    max_pairs=args.max_pairs,
                    artifact_name=args.artifact_name,
                )
            finally:
                engine.dispose()
            print(str(artifact))
            return 0
        if args.command == "run-controlled":
            print(json.dumps(asyncio.run(_run_controlled(args)), sort_keys=True))
            return 0
        observations = _load_observations(args.observations)
        result = score_duplicate_evaluation(
            observations,
            eligible_positive_pairs=args.eligible_positive_pairs,
            candidate_eligible_positive_pairs=(args.candidate_eligible_positive_pairs),
            candidate_recalled_positive_pairs=args.recalled_positive_pairs,
            real_reference_languages=set(args.real_reference_language),
        )
        if args.json_output.exists() or args.markdown_output.exists():
            raise FileExistsError("refusing to overwrite report output")
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        args.markdown_output.write_text(_markdown(result), encoding="utf-8")
        print(json.dumps({"decision": result["decision"]}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"Jev duplicate evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
