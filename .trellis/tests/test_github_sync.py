from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "hooks" / "github_sync.py"
SPEC = importlib.util.spec_from_file_location("github_sync", SCRIPT_PATH)
assert SPEC and SPEC.loader
github_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(github_sync)


class GithubSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / ".git").mkdir()
        self.task_dir = self.root / ".trellis" / "tasks" / "example-task"
        self.task_dir.mkdir(parents=True)
        self.task_json = self.task_dir / "task.json"
        self._write_task({"title": "Example task", "priority": "P2", "meta": {}})
        (self.task_dir / "prd.md").write_text(
            """# Example task

## Goal

Make the workflow observable.

## Requirements

- Create one issue.
- Keep the issue open for QA.

## Acceptance Criteria

- [ ] Issue body is public-safe.
""",
            encoding="utf-8",
        )
        # These files prove the renderer does not read non-allowlisted artifacts.
        (self.task_dir / "design.md").write_text("SECRET_DESIGN_VALUE", encoding="utf-8")
        (self.task_dir / "implement.md").write_text("SECRET_IMPLEMENT_VALUE", encoding="utf-8")
        self.env = mock.patch.dict(
            os.environ,
            {"TASK_JSON_PATH": str(self.task_json)},
            clear=False,
        )
        self.env.start()
        self.gh_calls: list[list[str]] = []
        self.comments: list[str] = []
        self.issue_state = "OPEN"

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def _write_task(self, payload: dict) -> None:
        self.task_json.parent.mkdir(parents=True, exist_ok=True)
        self.task_json.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def _fake_process(self, command, *, cwd, action):
        del cwd, action
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return github_sync.subprocess.CompletedProcess(
                command,
                0,
                stdout="git@github.com:example/project.git\n",
                stderr="",
            )
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return github_sync.subprocess.CompletedProcess(
                command,
                0,
                stdout="abc123\n",
                stderr="",
            )
        raise AssertionError(f"unexpected process: {command}")

    def _fake_gh(self, args, *, repo_root, repository, action):
        del repo_root, repository, action
        args = list(args)
        self.gh_calls.append(args)
        if args[:2] == ["issue", "create"]:
            body = args[args.index("--body") + 1]
            self.assertIn("Make the workflow observable.", body)
            self.assertNotIn("SECRET_DESIGN_VALUE", body)
            self.assertNotIn("SECRET_IMPLEMENT_VALUE", body)
            return "https://github.com/example/project/issues/42"
        if args[:2] == ["issue", "view"]:
            return json.dumps(
                {
                    "number": 42,
                    "state": self.issue_state,
                    "url": "https://github.com/example/project/issues/42",
                    "comments": [{"body": comment} for comment in self.comments],
                }
            )
        if args[:2] == ["issue", "comment"]:
            self.comments.append(args[args.index("--body") + 1])
            return ""
        if args[:2] == ["issue", "close"]:
            self.issue_state = "CLOSED"
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    def test_create_persists_binding_and_repeated_create_is_idempotent(self) -> None:
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(github_sync.main(["create"]), 0)
            self.assertEqual(github_sync.main(["create"]), 0)

        task = json.loads(self.task_json.read_text(encoding="utf-8"))
        self.assertEqual(task["meta"]["github_issue"], 42)
        self.assertEqual(
            task["meta"]["github_issue_url"],
            "https://github.com/example/project/issues/42",
        )
        self.assertEqual(
            sum(call[:2] == ["issue", "create"] for call in self.gh_calls),
            1,
        )

    def test_opt_out_makes_no_repository_or_github_call(self) -> None:
        self._write_task({"title": "Local-only task", "meta": {"github_issue": False}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=AssertionError),
            mock.patch.object(github_sync, "_run_gh", side_effect=AssertionError),
        ):
            self.assertEqual(github_sync.main(["create"]), 0)

    def test_create_failure_does_not_persist_a_fake_binding(self) -> None:
        self._write_task({"title": "Retryable task", "meta": {"existing": "value"}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(
                github_sync,
                "_run_gh",
                side_effect=github_sync.SyncError("gh auth is unavailable"),
            ),
        ):
            self.assertEqual(github_sync.main(["create"]), 1)

        task = json.loads(self.task_json.read_text(encoding="utf-8"))
        self.assertEqual(task["meta"], {"existing": "value"})

    def test_child_summary_references_parent_issue_without_cascading_state(self) -> None:
        parent_dir = self.task_dir.parent / "parent-task"
        parent_dir.mkdir()
        (parent_dir / "task.json").write_text(
            json.dumps({"title": "Parent", "meta": {"github_issue": 7}}),
            encoding="utf-8",
        )
        self._write_task(
            {"title": "Child", "parent": "parent-task", "meta": {}}
        )

        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(github_sync.main(["create"]), 0)

        create_call = next(call for call in self.gh_calls if call[:2] == ["issue", "create"])
        body = create_call[create_call.index("--body") + 1]
        self.assertIn("Parent issue: #7", body)

    def test_archive_comment_is_idempotent_and_does_not_close(self) -> None:
        self._write_task({"title": "Archive task", "meta": {"github_issue": 42}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(github_sync.main(["archive"]), 0)
            self.assertEqual(github_sync.main(["archive"]), 0)

        comments = [call for call in self.gh_calls if call[:2] == ["issue", "comment"]]
        closes = [call for call in self.gh_calls if call[:2] == ["issue", "close"]]
        self.assertEqual(len(comments), 1)
        self.assertEqual(closes, [])
        self.assertIn("abc123", comments[0][comments[0].index("--body") + 1])
        self.assertIn("Awaiting manual QA", comments[0][comments[0].index("--body") + 1])

    def test_closed_binding_warns_without_reopen_or_duplicate(self) -> None:
        self._write_task({"title": "Closed task", "meta": {"github_issue": 42}})

        def closed_issue(args, *, repo_root, repository, action):
            del repo_root, repository, action
            self.gh_calls.append(list(args))
            if list(args)[:2] == ["issue", "view"]:
                return json.dumps({"number": 42, "state": "CLOSED", "comments": []})
            raise AssertionError(f"unexpected gh call: {args}")

        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=closed_issue),
        ):
            self.assertEqual(github_sync.main(["archive"]), 1)
            self.assertEqual(github_sync.main(["qa-fail", "--notes", "broken"]), 1)

        self.assertFalse(any(call[:2] == ["issue", "close"] for call in self.gh_calls))
        self.assertFalse(any(call[:2] == ["issue", "comment"] for call in self.gh_calls))

    def test_qa_failure_stays_open_and_explicit_pass_closes(self) -> None:
        self._write_task({"title": "QA task", "meta": {"github_issue": 42}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(github_sync.main(["qa-fail", "--notes", "Found a regression"]), 0)
            self.assertEqual(github_sync.main(["qa-pass", "--notes", "Retest passed", "--close"]), 0)

        self.assertEqual(
            sum(call[:2] == ["issue", "comment"] for call in self.gh_calls),
            2,
        )
        self.assertEqual(
            sum(call[:2] == ["issue", "close"] for call in self.gh_calls),
            1,
        )

    def test_repeated_qa_pass_after_close_is_idempotent(self) -> None:
        self._write_task({"title": "QA task", "meta": {"github_issue": 42}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(
                github_sync.main(["qa-pass", "--notes", "Retest passed", "--close"]),
                0,
            )
            self.assertEqual(
                github_sync.main(["qa-pass", "--notes", "Retest passed", "--close"]),
                0,
            )

        comments = [call for call in self.gh_calls if call[:2] == ["issue", "comment"]]
        closes = [call for call in self.gh_calls if call[:2] == ["issue", "close"]]
        self.assertEqual(len(comments), 1)
        self.assertEqual(len(closes), 1)

    def test_qa_pass_requires_explicit_close_flag(self) -> None:
        self._write_task({"title": "QA task", "meta": {"github_issue": 42}})
        with (
            mock.patch.object(github_sync, "_run_process", side_effect=self._fake_process),
            mock.patch.object(github_sync, "_run_gh", side_effect=self._fake_gh),
        ):
            self.assertEqual(github_sync.main(["qa-pass", "--notes", "Looks good"]), 1)
        self.assertEqual(self.gh_calls, [])

    def test_repository_parser_accepts_https_and_ssh_remotes(self) -> None:
        self.assertEqual(
            github_sync._repository_from_remote("https://github.com/acme/app.git"),
            "acme/app",
        )
        self.assertEqual(
            github_sync._repository_from_remote("git@github.com:acme/app.git"),
            "acme/app",
        )


if __name__ == "__main__":
    unittest.main()
