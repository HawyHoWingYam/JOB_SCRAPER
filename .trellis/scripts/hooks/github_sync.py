#!/usr/bin/env python3
"""Synchronize Trellis task lifecycle events with GitHub Issues.

The task lifecycle runner intentionally treats this script as a best-effort
external integration: a non-zero exit is surfaced as a warning by Trellis but
does not block task creation, archive, or commit operations.

The script uses the authenticated ``gh`` CLI and never reads a token from the
repository.  ``TASK_JSON_PATH`` is supplied by ``run_task_hooks``.  Manual QA
actions are called by the project-local skill, not directly by the user.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


ISSUE_META_KEY = "github_issue"
ISSUE_URL_META_KEY = "github_issue_url"
OPT_OUT = False
ISSUE_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(?P<number>\d+)"
)
HEADING_PATTERN = re.compile(r"^##\s+(?P<title>[^\n]+?)\s*$", re.MULTILINE)
COMMENT_MARKER_PREFIX = "trellis-task:"


class SyncError(RuntimeError):
    """An external sync failure that should be rendered as a hook warning."""


def _task_json_path() -> Path:
    raw_path = os.environ.get("TASK_JSON_PATH", "").strip()
    if not raw_path:
        raise SyncError("TASK_JSON_PATH is not set")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise SyncError(f"task.json does not exist: {path}")
    return path


def _repo_root(task_path: Path) -> Path:
    for candidate in (task_path.parent, *task_path.parents):
        if (candidate / ".trellis").is_dir() and (candidate / ".git").exists():
            return candidate
    raise SyncError(f"could not locate repository root for {task_path}")


def _read_task(task_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"could not read task metadata: {task_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"task metadata must be a JSON object: {task_path}")
    return data


def _write_task(task_path: Path, task: dict[str, Any]) -> None:
    try:
        task_path.write_text(
            json.dumps(task, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise SyncError(f"could not persist task metadata: {task_path}: {exc}") from exc


def _task_opted_out(task: dict[str, Any]) -> bool:
    meta = task.get("meta")
    return isinstance(meta, dict) and meta.get(ISSUE_META_KEY) is OPT_OUT


def _issue_binding(task: dict[str, Any]) -> int | None:
    meta = task.get("meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get(ISSUE_META_KEY)
    if value is None or value is OPT_OUT:
        return None
    if isinstance(value, bool):
        raise SyncError(f"invalid {ISSUE_META_KEY} value: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SyncError(f"invalid {ISSUE_META_KEY} value: {value!r}") from exc
    if number <= 0:
        raise SyncError(f"invalid {ISSUE_META_KEY} value: {value!r}")
    return number


def _configured_repository(repo_root: Path) -> str | None:
    config_path = repo_root / ".trellis" / "hooks.local.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"invalid local hook config: {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise SyncError(f"local hook config must be a JSON object: {config_path}")
    github = config.get("github")
    if github is None:
        return None
    if not isinstance(github, dict):
        raise SyncError("hooks.local.json github entry must be an object")
    repository = github.get("repository")
    if repository is None:
        return None
    return _validate_repository(str(repository))


def _validate_repository(repository: str) -> str:
    normalized = re.sub(
        r"^https://github\.com/",
        "",
        repository.strip(),
        count=1,
        flags=re.IGNORECASE,
    )
    normalized = normalized.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized):
        raise SyncError(f"invalid GitHub repository: {repository!r}")
    return normalized


def _repository_from_remote(remote: str) -> str:
    value = remote.strip()
    match = re.search(
        r"github\.com[:/](?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$",
        value,
        re.IGNORECASE,
    )
    if not match:
        raise SyncError(f"origin is not a GitHub repository: {remote!r}")
    return _validate_repository(match.group("repository"))


def _resolve_repository(repo_root: Path) -> str:
    configured = _configured_repository(repo_root)
    if configured:
        return configured
    result = _run_process(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_root,
        action="resolve origin",
    )
    return _repository_from_remote(result.stdout)


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    action: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"{action} timed out after 60 seconds") from exc
    except OSError as exc:
        raise SyncError(f"{action} failed to start: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no details"
        raise SyncError(f"{action} failed: {detail}")
    return result


def _run_gh(
    args: Sequence[str],
    *,
    repo_root: Path,
    repository: str,
    action: str,
) -> str:
    result = _run_process(
        ["gh", *args, "--repo", repository],
        cwd=repo_root,
        action=action,
    )
    return result.stdout.strip()


def _extract_section(markdown: str, wanted_title: str) -> str | None:
    headings = list(HEADING_PATTERN.finditer(markdown))
    for index, heading in enumerate(headings):
        title = heading.group("title").strip()
        if title.casefold() != wanted_title.casefold():
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        content = markdown[start:end].strip()
        return content or None
    return None


def _relative_task_path(task_path: Path, repo_root: Path) -> str:
    try:
        return task_path.parent.relative_to(repo_root).as_posix()
    except ValueError:
        return task_path.parent.as_posix()


def _parent_issue(task_path: Path, task: dict[str, Any]) -> int | None:
    parent = task.get("parent")
    if not parent:
        return None
    parent_path = task_path.parent.parent / str(parent) / "task.json"
    if not parent_path.is_file():
        return None
    try:
        parent_task = _read_task(parent_path)
    except SyncError:
        return None
    return _issue_binding(parent_task)


def _render_public_body(task_path: Path, task: dict[str, Any], repo_root: Path) -> str:
    prd_path = task_path.parent / "prd.md"
    try:
        prd = prd_path.read_text(encoding="utf-8") if prd_path.is_file() else ""
    except OSError as exc:
        raise SyncError(f"could not read PRD: {prd_path}: {exc}") from exc

    title = str(task.get("title") or task.get("name") or "Untitled Trellis task").strip()
    lines = [
        f"Trellis task: `{_relative_task_path(task_path, repo_root)}`",
        f"Priority: `{task.get('priority') or 'unspecified'}`",
    ]
    parent_issue = _parent_issue(task_path, task)
    if parent_issue is not None:
        lines.append(f"Parent issue: #{parent_issue}")

    sections = [("Goal", "Goal"), ("Requirements", "Requirements"), ("Acceptance Criteria", "Acceptance Criteria")]
    for heading, source_heading in sections:
        content = _extract_section(prd, source_heading)
        if content:
            lines.extend(["", f"## {heading}", content])
    return f"# {title}\n\n" + "\n".join(lines).strip() + "\n"


def _issue_view(
    issue: int,
    *,
    repo_root: Path,
    repository: str,
) -> dict[str, Any]:
    output = _run_gh(
        ["issue", "view", str(issue), "--json", "number,state,url,comments"],
        repo_root=repo_root,
        repository=repository,
        action=f"read GitHub issue #{issue}",
    )
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SyncError(f"GitHub returned invalid issue JSON for #{issue}: {output!r}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"GitHub returned invalid issue data for #{issue}")
    return data


def _require_open_issue(
    issue: int,
    *,
    repo_root: Path,
    repository: str,
) -> dict[str, Any]:
    data = _issue_view(issue, repo_root=repo_root, repository=repository)
    if str(data.get("state", "")).upper() != "OPEN":
        raise SyncError(
            f"bound GitHub issue #{issue} is not open; refusing to reopen or duplicate it"
        )
    return data


def _comment_bodies(issue_data: dict[str, Any]) -> list[str]:
    comments = issue_data.get("comments")
    if not isinstance(comments, list):
        return []
    return [
        str(comment.get("body", ""))
        for comment in comments
        if isinstance(comment, dict)
    ]


def _append_comment(
    issue: int,
    body: str,
    marker: str,
    *,
    repo_root: Path,
    repository: str,
) -> bool:
    data = _require_open_issue(issue, repo_root=repo_root, repository=repository)
    if any(marker in comment for comment in _comment_bodies(data)):
        return False
    _run_gh(
        ["issue", "comment", str(issue), "--body", f"{body}\n\n<!-- {marker} -->"],
        repo_root=repo_root,
        repository=repository,
        action=f"comment on GitHub issue #{issue}",
    )
    return True


def _task_commit(repo_root: Path) -> str:
    return _run_process(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        action="read current commit",
    ).stdout.strip()


def _persist_binding(task_path: Path, task: dict[str, Any], issue: int, url: str) -> None:
    meta = task.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        task["meta"] = meta
    meta[ISSUE_META_KEY] = issue
    meta[ISSUE_URL_META_KEY] = url
    _write_task(task_path, task)


def cmd_create() -> None:
    task_path = _task_json_path()
    task = _read_task(task_path)
    if _task_opted_out(task):
        print("GitHub issue sync opted out by task metadata")
        return
    repo_root = _repo_root(task_path)
    repository = _resolve_repository(repo_root)
    existing = _issue_binding(task)
    if existing is not None:
        _require_open_issue(existing, repo_root=repo_root, repository=repository)
        print(f"GitHub issue already linked: #{existing}")
        return

    title = str(task.get("title") or task.get("name") or "Untitled Trellis task").strip()
    body = _render_public_body(task_path, task, repo_root)
    output = _run_gh(
        ["issue", "create", "--title", title, "--body", body],
        repo_root=repo_root,
        repository=repository,
        action="create GitHub issue",
    )
    match = ISSUE_URL_PATTERN.search(output)
    if not match:
        raise SyncError(f"could not parse issue URL from gh output: {output!r}")
    issue_repository = _validate_repository(match.group("repository"))
    if issue_repository.casefold() != repository.casefold():
        raise SyncError(
            "gh returned an issue URL for a different repository: "
            f"{issue_repository!r} (expected {repository!r})"
        )
    issue = int(match.group("number"))
    url = match.group(0)
    _persist_binding(task_path, task, issue, url)
    print(f"Created GitHub issue #{issue}: {url}")


def cmd_archive() -> None:
    task_path = _task_json_path()
    task = _read_task(task_path)
    if _task_opted_out(task):
        print("GitHub issue sync opted out by task metadata")
        return
    issue = _issue_binding(task)
    if issue is None:
        raise SyncError("task has no GitHub issue binding; archive update skipped")
    repo_root = _repo_root(task_path)
    repository = _resolve_repository(repo_root)
    commit = _task_commit(repo_root)
    task_ref = _relative_task_path(task_path, repo_root)
    marker = f"{COMMENT_MARKER_PREFIX}{task_ref}:archive:{commit}"
    body = (
        "Implementation archived and committed.\n\n"
        f"Trellis task: `{task_ref}`\n"
        f"Commit: `{commit}`\n\n"
        "Awaiting manual QA. This update does not assert that the branch was pushed."
    )
    posted = _append_comment(
        issue,
        body,
        marker,
        repo_root=repo_root,
        repository=repository,
    )
    print(f"GitHub issue #{issue} archive update {'posted' if posted else 'already present'}")


def _qa_marker(task_path: Path, repo_root: Path, event: str, notes: str) -> str:
    digest = hashlib.sha256(notes.encode("utf-8")).hexdigest()[:16]
    return f"{COMMENT_MARKER_PREFIX}{_relative_task_path(task_path, repo_root)}:qa:{event}:{digest}"


def _qa_context(task_path: Path) -> tuple[dict[str, Any], int, Path, str]:
    task = _read_task(task_path)
    if _task_opted_out(task):
        raise SyncError("task opted out of GitHub issue sync")
    issue = _issue_binding(task)
    if issue is None:
        raise SyncError("task has no GitHub issue binding")
    repo_root = _repo_root(task_path)
    repository = _resolve_repository(repo_root)
    return task, issue, repo_root, repository


def cmd_qa_fail(notes: str) -> None:
    if not notes.strip():
        raise SyncError("QA failure details are required")
    task_path = _task_json_path()
    _task, issue, repo_root, repository = _qa_context(task_path)
    marker = _qa_marker(task_path, repo_root, "fail", notes)
    body = f"Manual QA failed.\n\n{notes.strip()}"
    posted = _append_comment(
        issue,
        body,
        marker,
        repo_root=repo_root,
        repository=repository,
    )
    print(f"GitHub issue #{issue} QA failure {'posted' if posted else 'already present'}; issue remains open")


def cmd_qa_pass(notes: str, close: bool) -> None:
    if not close:
        raise SyncError("QA pass requires explicit closure intent (--close)")
    if not notes.strip():
        raise SyncError("QA pass evidence is required")
    task_path = _task_json_path()
    _task, issue, repo_root, repository = _qa_context(task_path)
    marker = _qa_marker(task_path, repo_root, "pass", notes)
    body = f"Manual QA passed.\n\n{notes.strip()}"
    issue_data = _issue_view(issue, repo_root=repo_root, repository=repository)
    issue_is_open = str(issue_data.get("state", "")).upper() == "OPEN"
    if not issue_is_open:
        if any(marker in comment for comment in _comment_bodies(issue_data)):
            print(f"GitHub issue #{issue} is already closed after manual QA approval")
            return
        raise SyncError(
            f"bound GitHub issue #{issue} is not open; refusing to reopen or duplicate it"
        )
    _append_comment(
        issue,
        body,
        marker,
        repo_root=repo_root,
        repository=repository,
    )
    _run_gh(
        ["issue", "close", str(issue)],
        repo_root=repo_root,
        repository=repository,
        action=f"close GitHub issue #{issue}",
    )
    print(f"Closed GitHub issue #{issue} after explicit manual QA approval")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "archive"):
        subparsers.add_parser(action)
    qa_fail = subparsers.add_parser("qa-fail")
    qa_fail.add_argument("--notes", required=True)
    qa_pass = subparsers.add_parser("qa-pass")
    qa_pass.add_argument("--notes", required=True)
    qa_pass.add_argument("--close", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.action == "create":
            cmd_create()
        elif args.action == "archive":
            cmd_archive()
        elif args.action == "qa-fail":
            cmd_qa_fail(args.notes)
        elif args.action == "qa-pass":
            cmd_qa_pass(args.notes, args.close)
        else:  # pragma: no cover - argparse enforces the action choices
            raise SyncError(f"unknown action: {args.action}")
    except SyncError as exc:
        print(f"GitHub issue sync warning: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
