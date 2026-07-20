from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import Any, Literal

from app.job_intelligence.cutover.contracts import WriterStateEvidence


WriterState = Literal["stopped", "running", "unknown"]
EvidenceKind = Literal["process", "container", "heartbeat"]


def _run_command(
    args: tuple[str, ...],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


class SystemWriterStateProvider:
    """Observe known writer containers/processes and fail closed on uncertainty."""

    _SERVICE_BY_WRITER = {
        "api": "backend-api",
        "embedding-worker": "embedding-worker",
        "enrichment-worker": "enrichment-worker",
        "ingest-worker": "ingest-worker",
        "scheduler-worker": "scheduler-worker",
        "scrapyd": "scrapyd",
    }
    _PROCESS_PATTERN_BY_WRITER = {
        "manual-action-helper": "app.workers.run_manual_action_helper",
        "source-catalog-admin": "source_catalog_admin",
    }

    def __init__(
        self,
        *,
        command_runner: Callable[..., Any] = _run_command,
        compose_directory: Path | None = None,
    ) -> None:
        self.command_runner = command_runner
        self.compose_directory = (
            compose_directory or Path(__file__).resolve().parents[4]
        )

    def collect(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> tuple[WriterStateEvidence, ...]:
        try:
            defined = self._defined_services()
            service_states = self._service_states()
            process_output = str(
                self.command_runner(
                    ("ps", "-eo", "pid=,args="),
                    cwd=self.compose_directory,
                ).stdout
                or ""
            )
        except Exception:
            return tuple(
                WriterStateEvidence(
                    writer=writer,
                    state="unknown",
                    evidence_kind="process",
                    evidence_ref="writer-probe:observation-failed",
                    observed_at=observed_at,
                )
                for writer in writers
            )

        observed: dict[str, tuple[WriterState, EvidenceKind, str]] = {}
        for writer, service in self._SERVICE_BY_WRITER.items():
            state = self._container_state(
                service,
                defined=defined,
                observed_states=service_states.get(service, ()),
            )
            observed[writer] = (
                state,
                "container",
                f"docker-compose:{service}:{state}",
            )

        scrapyd_state = observed["scrapyd"][0]
        for writer in ("detail-worker", "listing-worker"):
            observed[writer] = (
                scrapyd_state,
                "container",
                f"docker-compose:scrapyd:{scrapyd_state}",
            )

        for writer, pattern in self._PROCESS_PATTERN_BY_WRITER.items():
            process_state: WriterState = (
                "running" if pattern in process_output else "stopped"
            )
            observed[writer] = (
                process_state,
                "process",
                f"process-pattern:{pattern}:{process_state}",
            )

        outbox_dependencies = (
            "api",
            "embedding-worker",
            "enrichment-worker",
            "ingest-worker",
            "scheduler-worker",
            "source-catalog-admin",
        )
        dependency_states = tuple(observed[name][0] for name in outbox_dependencies)
        outbox_state: WriterState
        if "running" in dependency_states:
            outbox_state = "running"
        elif "unknown" in dependency_states:
            outbox_state = "unknown"
        else:
            outbox_state = "stopped"
        observed["outbox-publisher"] = (
            outbox_state,
            "container",
            f"writer-aggregate:outbox-publisher:{outbox_state}",
        )

        result: list[WriterStateEvidence] = []
        for writer in writers:
            state, evidence_kind, evidence_ref = observed.get(
                writer,
                ("unknown", "process", "writer-probe:writer-not-mapped"),
            )
            result.append(
                WriterStateEvidence(
                    writer=writer,
                    state=state,
                    evidence_kind=evidence_kind,
                    evidence_ref=evidence_ref,
                    observed_at=observed_at,
                )
            )
        return tuple(result)

    def _defined_services(self) -> set[str]:
        result = self.command_runner(
            ("docker", "compose", "config", "--services"),
            cwd=self.compose_directory,
        )
        return {
            line.strip()
            for line in str(result.stdout or "").splitlines()
            if line.strip()
        }

    def _service_states(self) -> dict[str, tuple[str, ...]]:
        result = self.command_runner(
            ("docker", "compose", "ps", "--all", "--format", "json"),
            cwd=self.compose_directory,
        )
        rows = self._json_rows(str(result.stdout or ""))
        states: dict[str, list[str]] = {}
        for row in rows:
            service = str(row.get("Service") or row.get("service") or "").strip()
            state = str(row.get("State") or row.get("state") or "").strip()
            if service:
                states.setdefault(service, []).append(state)
        return {service: tuple(values) for service, values in states.items()}

    @staticmethod
    def _json_rows(payload: str) -> tuple[dict[str, Any], ...]:
        stripped = payload.strip()
        if not stripped:
            return ()
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = [
                json.loads(line) for line in stripped.splitlines() if line.strip()
            ]
        if isinstance(decoded, dict):
            decoded = [decoded]
        if not isinstance(decoded, list) or any(
            not isinstance(row, dict) for row in decoded
        ):
            raise ValueError("docker compose ps returned an invalid JSON payload")
        return tuple(decoded)

    @staticmethod
    def _container_state(
        service: str,
        *,
        defined: set[str],
        observed_states: tuple[str, ...],
    ) -> WriterState:
        if service not in defined:
            return "unknown"
        if not observed_states:
            return "stopped"
        normalized = tuple(state.strip().casefold() for state in observed_states)
        if any(state.startswith(("running", "restarting")) for state in normalized):
            return "running"
        if all(
            state.startswith(("exited", "stopped", "dead", "created"))
            for state in normalized
        ):
            return "stopped"
        return "unknown"


class SystemWriterControl:
    """Explicitly restart persistent Compose writers, then verify their state."""

    _PERSISTENT_SERVICES = (
        "backend-api",
        "scheduler-worker",
        "ingest-worker",
        "enrichment-worker",
        "embedding-worker",
        "scrapyd",
    )

    def __init__(
        self,
        *,
        command_runner: Callable[..., Any] = _run_command,
        compose_directory: Path | None = None,
    ) -> None:
        self.command_runner = command_runner
        self.compose_directory = (
            compose_directory or Path(__file__).resolve().parents[4]
        )

    def reopen(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> dict[str, object]:
        self.command_runner(
            ("docker", "compose", "start", *self._PERSISTENT_SERVICES),
            cwd=self.compose_directory,
        )
        evidence = SystemWriterStateProvider(
            command_runner=self.command_runner,
            compose_directory=self.compose_directory,
        ).collect(writers=writers, observed_at=observed_at)
        states = {item.writer: item.state for item in evidence}
        if set(states) != set(writers) or "unknown" in states.values():
            raise RuntimeError("Writer restart evidence is incomplete or uncertain")
        expected_running = {
            "api",
            "detail-worker",
            "embedding-worker",
            "enrichment-worker",
            "ingest-worker",
            "listing-worker",
            "outbox-publisher",
            "scheduler-worker",
            "scrapyd",
        }
        if any(states.get(writer) != "running" for writer in expected_running):
            raise RuntimeError("Persistent writer services did not all restart")
        return {
            "status": "reopened",
            "writer_states": states,
        }


__all__ = ["SystemWriterControl", "SystemWriterStateProvider"]
