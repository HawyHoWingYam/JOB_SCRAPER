#!/usr/bin/env python3
"""One-time sandbox retention cutover."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.job_intelligence.sandbox_cutover import (  # noqa: E402
    RedisRuntimeStateCleaner,
    SandboxCutover,
    clear_database,
    verify_target_state,
)
from app.utils.redis_client import RedisClient  # noqa: E402
from scripts.bootstrap_db import bootstrap_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export")
    export.add_argument("--output", type=Path, required=True)

    clear_redis = commands.add_parser("clear-redis")
    clear_redis.add_argument("--confirm-services-stopped", action="store_true")

    clear_db = commands.add_parser("clear-database")
    clear_db.add_argument("--artifact", type=Path, required=True)
    clear_db.add_argument("--confirm-services-stopped", action="store_true")
    clear_db.add_argument("--confirm-destroy-sandbox", action="store_true", required=True)

    commands.add_parser("bootstrap")

    import_command = commands.add_parser("import")
    import_command.add_argument("--artifact", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--artifact", type=Path, required=True)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--artifact", type=Path, required=True)
    return parser


def _cutover() -> SandboxCutover:
    return SandboxCutover(source_engine=engine, metadata=Base.metadata)


def _emit(payload: object) -> None:
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)  # type: ignore[arg-type]
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _require_services_stopped(confirmed: bool) -> None:
    if not confirmed:
        raise RuntimeError(
            "Refusing destructive sandbox cleanup until all services are stopped"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cutover = _cutover()
    if args.command == "export":
        result = cutover.export_retained(args.output)
    elif args.command == "clear-redis":
        _require_services_stopped(args.confirm_services_stopped)
        result = RedisRuntimeStateCleaner(
            RedisClient(redis_url=settings.redis_url).redis
        ).clear()
    elif args.command == "clear-database":
        _require_services_stopped(args.confirm_services_stopped)
        cutover.validate_artifact(args.artifact)
        clear_database(db_engine=engine, confirmed=args.confirm_destroy_sandbox)
        result = {"cleared": True}
    elif args.command == "bootstrap":
        bootstrap_database(db_engine=engine, metadata=Base.metadata)
        result = {"bootstrapped": True}
    elif args.command == "import":
        result = cutover.import_retained(args.artifact, target_engine=engine)
    else:
        retention = cutover.verify_retained(args.artifact, target_engine=engine)
        target = verify_target_state(db_engine=engine, metadata=Base.metadata)
        if not retention.matched or not target.clean:
            raise RuntimeError(
                "Sandbox verification failed: "
                + "; ".join((*retention.mismatches, *target.issues))
            )
        if args.command == "finalize":
            cutover.delete_artifact_after_verification(args.artifact, retention)
        result = {
            "retention": asdict(retention),
            "target": asdict(target),
            "artifact_deleted": args.command == "finalize",
        }
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
