#!/usr/bin/env python3
"""Controlled Job Intelligence inventory, cutover, verification, and rollback plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.cutover import (  # noqa: E402
    ApplicationIdentity,
    JobIntelligenceCutover,
    PostgresCutoverEnvironment,
    RebuildIdentity,
)
from app.job_intelligence.cutover.artifacts import (  # noqa: E402
    CutoverManifestStore,
    ManifestIntegrityError,
    VerifiedArtifactStore,
)
from app.job_intelligence.cutover.writer_probe import (  # noqa: E402
    SystemWriterControl,
)


def _add_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)


def _add_checkpoint_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkpoint-dir", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "human"), default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--application-commit", required=True)
    inventory.add_argument("--application-image", required=True)
    inventory.add_argument("--configuration-hash", required=True)
    inventory.add_argument("--target-schema-revision", required=True)
    _add_rebuild_arguments(inventory)

    dry_run = subparsers.add_parser("dry-run")
    _add_manifest_argument(dry_run)
    _add_checkpoint_argument(dry_run)

    execute = subparsers.add_parser("execute")
    _add_manifest_argument(execute)
    _add_checkpoint_argument(execute)
    execute.add_argument("--backup-id", required=True)
    execute.add_argument("--restore-database-url", required=True)
    execute.add_argument("--confirm-manifest-hash", required=True)
    execute.add_argument("--runtime-evidence", type=Path)
    execute.add_argument("--confirm-execute", action="store_true", required=True)
    execute.add_argument(
        "--confirm-reopen-writers",
        action="store_true",
    )

    verify = subparsers.add_parser("verify")
    _add_manifest_argument(verify)
    _add_checkpoint_argument(verify)
    verify.add_argument("--runtime-evidence", type=Path)

    rollback = subparsers.add_parser("rollback-plan")
    _add_manifest_argument(rollback)
    _add_checkpoint_argument(rollback)
    return parser


def _add_rebuild_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-attributes-version", default="v1")
    parser.add_argument(
        "--canonical-taxonomy-version",
        default="canonical-job-taxonomy-v1",
    )
    parser.add_argument(
        "--company-industry-version",
        default="hsic-v2.0-2026-07-19",
    )
    parser.add_argument("--skill-version", default="skills-2026-07-19-v1")
    parser.add_argument("--embedding-model", default="all-MiniLM-L6-v2")
    parser.add_argument("--embedding-version", type=int, default=1)


def _environment_for_inventory(args) -> PostgresCutoverEnvironment:
    return PostgresCutoverEnvironment(
        session_factory=SessionLocal,
        database_url=settings.database_url,
        application=ApplicationIdentity(
            commit=args.application_commit,
            image=args.application_image,
            configuration_hash=args.configuration_hash,
        ),
        target_schema_revision=args.target_schema_revision,
        rebuild=RebuildIdentity(
            source_attributes=args.source_attributes_version,
            canonical_taxonomy=args.canonical_taxonomy_version,
            company_industry=args.company_industry_version,
            skills=args.skill_version,
            embedding_model=args.embedding_model,
            embedding_version=args.embedding_version,
        ),
    )


def _environment_from_manifest(
    manifest_path: Path,
    *,
    execute: bool = False,
    reopen_writers: bool = False,
) -> PostgresCutoverEnvironment:
    manifest = CutoverManifestStore().read(manifest_path).manifest
    embedding_model: Any = None
    writer_control: Any = None
    if execute:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        embedding_model = SentenceTransformer(manifest.rebuild.embedding_model)
    if reopen_writers:
        writer_control = SystemWriterControl()
    return PostgresCutoverEnvironment(
        session_factory=SessionLocal,
        database_url=settings.database_url,
        application=manifest.application,
        target_schema_revision=manifest.schema_identity.target_revision,
        rebuild=manifest.rebuild,
        embedding_model=embedding_model,
        writer_control=writer_control,
    )


def _copy_runtime_evidence(source: Path, checkpoint_dir: Path) -> None:
    store = VerifiedArtifactStore()
    try:
        payload = store.read(source)
    except ManifestIntegrityError:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Runtime evidence must be a JSON object")
    store.write(checkpoint_dir / "runtime-smoke-evidence.json", payload)


def _render_human(command: str, payload: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"Job Intelligence cutover: {command}",
            *(
                f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"
                for key, value in sorted(payload.items())
            ),
        )
    )


def _emit(command: str, payload: dict[str, Any], *, output_format: str) -> None:
    if output_format == "human":
        print(_render_human(command, payload))
    else:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result: Any
    try:
        if args.command == "inventory":
            cutover = JobIntelligenceCutover(
                environment=_environment_for_inventory(args)
            )
            result = cutover.inventory(output=args.output)
        else:
            if args.command in {"execute", "verify"} and args.runtime_evidence:
                _copy_runtime_evidence(args.runtime_evidence, args.checkpoint_dir)
            environment = _environment_from_manifest(
                args.manifest,
                execute=args.command == "execute",
                reopen_writers=(
                    args.confirm_reopen_writers if args.command == "execute" else False
                ),
            )
            cutover = JobIntelligenceCutover(environment=environment)
            if args.command == "dry-run":
                result = cutover.dry_run(
                    manifest_path=args.manifest,
                    checkpoint_dir=args.checkpoint_dir,
                )
            elif args.command == "execute":
                result = cutover.execute(
                    manifest_path=args.manifest,
                    checkpoint_dir=args.checkpoint_dir,
                    backup_id=args.backup_id,
                    restore_database_url=args.restore_database_url,
                    confirm_execute=args.confirm_execute,
                    confirm_manifest_hash=args.confirm_manifest_hash,
                )
            elif args.command == "verify":
                result = cutover.verify(
                    manifest_path=args.manifest,
                    checkpoint_dir=args.checkpoint_dir,
                )
            else:
                result = cutover.rollback_plan(
                    manifest_path=args.manifest,
                    checkpoint_dir=args.checkpoint_dir,
                )
        payload = result.model_dump(mode="json")
        _emit(args.command, payload, output_format=args.format)
        return 0
    except Exception as exc:
        error = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": "Cutover command failed; inspect verified checkpoint artifacts",
        }
        print(
            json.dumps(error, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
