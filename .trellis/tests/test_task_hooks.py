from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from unittest import mock
import unittest


SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import task_utils  # noqa: E402


class TaskHookRunnerTests(unittest.TestCase):
    def test_hook_receives_task_path_and_does_not_raise_on_failure(self) -> None:
        task_json = Path("/tmp/example-task/task.json")
        repo_root = Path("/tmp/example-repo")
        failed = subprocess.CompletedProcess(
            ["python3", "hook.py"],
            1,
            stdout="",
            stderr="gh unavailable",
        )

        with (
            mock.patch("subprocess.run", return_value=failed) as run,
            mock.patch("common.config.get_hooks", return_value=["python3 hook.py"]),
        ):
            task_utils.run_task_hooks("after_start", task_json, repo_root)

        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["cwd"], repo_root)
        self.assertEqual(kwargs["env"]["TASK_JSON_PATH"], str(task_json))
        self.assertEqual(kwargs["shell"], True)


if __name__ == "__main__":
    unittest.main()
