from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
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
from app.services.jev_evaluation import (  # noqa: E402
    EvaluationObservation,
    load_controlled_cases,
    score_evaluation,
    write_json,
)
from app.services.jev_evaluation_corpus import (  # noqa: E402
    build_real_corpus_artifact,
    verify_real_corpus_artifact,
)
from app.services.jev_evaluation_runner import JevEvaluationRunner  # noqa: E402
from app.services.jev_runtime_settings_service import (  # noqa: E402
    JevRuntimeSettingsService,
)


def _artifact_hash(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_observations(path: Path) -> list[EvaluationObservation]:
    observations = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            observations.append(EvaluationObservation.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid observation line {line_number}: {exc}") from exc
    return observations


def _write_observations(path: Path, observations: list[EvaluationObservation]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite observation artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(item.model_dump(), ensure_ascii=False, sort_keys=True) + "\n"
            for item in observations
        ),
        encoding="utf-8",
    )


def _verify_observation_manifest(
    controlled: Path, observations: list[EvaluationObservation]
) -> None:
    load_controlled_cases(controlled)
    expected = _artifact_hash(controlled)
    observed = {
        item.manifest_sha256
        for item in observations
        if item.manifest_sha256 is not None
    }
    if any(item.manifest_sha256 is None for item in observations) or observed != {
        expected
    }:
        raise ValueError("observation manifest hash does not match controlled artifact")


def _report_markdown(report: dict[str, object]) -> str:
    execution = report["execution"]
    lines = [
        "# Jev Skill evaluation report",
        "",
        f"Decision: **{report['decision']}**",
        "",
        "## Execution",
        "",
        f"Eligible observations: {execution['eligible']}; answered: "
        f"{execution['answered']}; abstained: {execution['abstained']}; "
        f"unavailable: {execution['unavailable']}; invalid: {execution['invalid']}.",
        "",
        f"Tokens: {execution['input_tokens']} input / "
        f"{execution['output_tokens']} output. Provider-reported microdollars: "
        f"{execution['provider_reported_microdollars']}.",
        "",
        f"Latency p50/p95 ms: {execution['latency_ms_p50'] or 'not_evaluable'} / "
        f"{execution['latency_ms_p95'] or 'not_evaluable'}.",
        "",
        "## Controlled held-out",
        "",
        "| Decision | Eligible | Answered | Correct | Answered correctness | Coverage | Technical failure |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind, metrics in report["controlled"].items():
        lines.append(
            f"| {kind} | {metrics['eligible']} | {metrics['answered']} | "
            f"{metrics['correct']} | {metrics['answered_correctness'] or 'not_evaluable'} | "
            f"{metrics['actionable_coverage'] or 'not_evaluable'} | "
            f"{metrics['technical_failure_rate'] or 'not_evaluable'} |"
        )
    stability = report["option_reordering_stability"]
    lines.extend(
        [
            "",
            "## Option-order stability",
            "",
            f"{stability['stable_groups']}/{stability['eligible_groups']} stable groups "
            f"({stability['rate'] or 'not_evaluable'}).",
            "",
            "## Limitations",
            "",
            *[f"- {value}" for value in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def _credential(path: Path | None) -> str:
    if path is not None:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"Authorization:\s*Bearer\s+(\S+)", text, re.IGNORECASE)
        if not match:
            raise ValueError("credential file does not contain a bearer token")
        return match.group(1)
    value = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not value:
        raise ValueError("TYPESAFE_API_KEY or --credential-file is required")
    return value


def _evaluation_session(args, api_key: str):
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


async def _run_paid(args) -> dict[str, object]:
    if not args.confirm_paid_evaluation:
        raise ValueError("run requires --confirm-paid-evaluation")
    cases = [
        case
        for case in load_controlled_cases(args.controlled)
        if case.split == args.split
    ][: args.limit]
    if not cases:
        raise ValueError("no controlled cases selected")
    key = _credential(args.credential_file)
    engine, db = _evaluation_session(args, key)
    client = NativeSystemOneClient(
        endpoint=args.endpoint,
        api_key=key,
        http_client=httpx.AsyncClient(timeout=args.timeout_seconds),
    )
    try:
        runner = JevEvaluationRunner(db)
        run = runner.start(
            cases=cases,
            manifest_sha256=_artifact_hash(args.controlled),
        )
        db.commit()
        await runner.execute_remaining(run.id, evaluator=client)
        db.commit()
        observations = runner.observations(run.id)
        _write_observations(args.output, observations)
        return {
            "selected": len(cases),
            "completed_observations": len(observations),
            "stopped_early": len(observations) < len(cases),
        }
    finally:
        await client.aclose()
        db.close()
        engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Jev Skill evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--controlled", type=Path, required=True)
    validate.add_argument("--real-artifact", type=Path)

    plan = sub.add_parser("plan")
    plan.add_argument("--controlled", type=Path, required=True)
    plan.add_argument(
        "--split", choices=("development", "held_out"), default="development"
    )
    plan.add_argument("--limit", type=int, default=1)

    export = sub.add_parser("export-real")
    export.add_argument("--database-url", required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--limit", type=int, default=100)

    run = sub.add_parser("run")
    run.add_argument("--controlled", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--state-db", type=Path, required=True)
    run.add_argument(
        "--split", choices=("development", "held_out"), default="development"
    )
    run.add_argument("--limit", type=int, default=1)
    run.add_argument("--endpoint", default="https://www.rsiai.net/v1/systemone")
    run.add_argument("--model", default="jev-latest")
    run.add_argument("--credential-file", type=Path)
    run.add_argument("--timeout-seconds", type=int, default=30)
    run.add_argument("--confirm-paid-evaluation", action="store_true")

    report = sub.add_parser("report")
    report.add_argument("--controlled", type=Path, required=True)
    report.add_argument("--observations", type=Path, required=True)
    report.add_argument("--json-output", type=Path, required=True)
    report.add_argument("--markdown-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            cases = load_controlled_cases(args.controlled)
            result = {"controlled_cases": len(cases), "valid": True}
            if args.real_artifact:
                result["real_rows"] = verify_real_corpus_artifact(args.real_artifact)[
                    "manifest"
                ]["row_count"]
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "plan":
            cases = [
                case
                for case in load_controlled_cases(args.controlled)
                if case.split == args.split
            ][: args.limit]
            result = {
                "selected": len(cases),
                "monetary_authority": "jev_api_console",
                "paid_requests_started": 0,
            }
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "export-real":
            engine = create_engine(args.database_url)
            try:
                artifact = build_real_corpus_artifact(
                    engine,
                    output_dir=args.output_dir,
                    limit=args.limit,
                )
            finally:
                engine.dispose()
            print(str(artifact))
            return 0
        if args.command == "run":
            print(json.dumps(asyncio.run(_run_paid(args)), sort_keys=True))
            return 0
        observations = _load_observations(args.observations)
        _verify_observation_manifest(args.controlled, observations)
        result = score_evaluation(observations)
        if args.json_output.exists() or args.markdown_output.exists():
            raise FileExistsError("refusing to overwrite report output")
        write_json(args.json_output, result)
        args.markdown_output.write_text(_report_markdown(result), encoding="utf-8")
        print(json.dumps({"decision": result["decision"]}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"jev evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
