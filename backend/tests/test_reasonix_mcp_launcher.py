from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tomllib


MODULE_PATH = Path(__file__).resolve().parents[2] / ".reasonix" / "scripts" / "reasonix_mcp_launcher.py"
SPEC = importlib.util.spec_from_file_location("reasonix_mcp_launcher", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_postgres_env_from_database_url():
    parsed = MODULE.parse_database_url("postgresql://admin:dev_password@localhost:5433/jobsdb")

    assert parsed == {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5433",
        "POSTGRES_USER": "admin",
        "POSTGRES_PASSWORD": "dev_password",
        "POSTGRES_DB": "jobsdb",
    }


def test_resolve_launch_spec_uses_repo_env_for_redis_and_postgres(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb",
                "REDIS_URL=redis://localhost:6379/0",
            ]
        ),
        encoding="utf-8",
    )

    redis_spec = MODULE.resolve_launch_spec("redis", repo_root=repo_root, ensure_installed=False)
    postgres_spec = MODULE.resolve_launch_spec("postgres", repo_root=repo_root, ensure_installed=False)

    assert redis_spec.args == ["--url", "redis://localhost:6379/0"]
    assert redis_spec.env["REDIS_URL"] == "redis://localhost:6379/0"
    assert postgres_spec.args == []
    assert postgres_spec.env["POSTGRES_HOST"] == "localhost"
    assert postgres_spec.env["POSTGRES_PORT"] == "5433"
    assert postgres_spec.env["POSTGRES_USER"] == "admin"
    assert postgres_spec.env["POSTGRES_PASSWORD"] == "dev_password"
    assert postgres_spec.env["POSTGRES_DB"] == "jobsdb"


def test_build_child_env_prepends_venv_scripts_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    spec = MODULE.LaunchSpec(
        server="semgrep",
        executable="semgrep-mcp",
        args=[],
        env={},
        venv_dir=tmp_path / "semgrep",
        package_spec="semgrep-mcp==0.9.0",
    )

    child_env = MODULE.build_child_env(spec)

    expected_prefix = str(MODULE.venv_bin_dir(spec.venv_dir))
    assert child_env["PATH"].split(MODULE.os.pathsep)[0] == expected_prefix
    assert r"C:\Windows\System32" in child_env["PATH"]


def test_ensure_python_server_installs_mismatched_semgrep_runtime_dependency(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runtime_dir = tmp_path / "venvs"
    scripts_dir = runtime_dir / "semgrep" / ("Scripts" if MODULE.os.name == "nt" else "bin")
    scripts_dir.mkdir(parents=True)
    python_path = scripts_dir / ("python.exe" if MODULE.os.name == "nt" else "python")
    python_path.write_text("", encoding="utf-8")
    entrypoint_path = scripts_dir / ("semgrep.exe" if MODULE.os.name == "nt" else "semgrep")
    entrypoint_path.write_text("", encoding="utf-8")

    commands: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(MODULE, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(MODULE, "run_command", lambda args, *, cwd: commands.append((args, cwd)))
    monkeypatch.setattr(
        MODULE,
        "package_version",
        lambda _python_path, package_name: {
            "semgrep": "1.135.0",
            "mcp": None,
            "setuptools": "82.0.1",
        }[package_name],
    )

    MODULE.ensure_python_server("semgrep", repo_root=repo_root, bootstrap_python="python")

    assert len(commands) == 1
    install_args, cwd = commands[0]
    assert install_args[:5] == [
        str(python_path),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    assert install_args[-2:] == ["mcp==1.12.2", "setuptools<81"]
    assert cwd == repo_root


def test_resolve_launch_spec_uses_semgrep_shim_entrypoint(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    spec = MODULE.resolve_launch_spec("semgrep", repo_root=repo_root, ensure_installed=False)

    assert Path(spec.executable).name == ("python.exe" if MODULE.os.name == "nt" else "python")
    assert spec.args == ["-u", str(MODULE.ROOT_DIR / ".reasonix" / "scripts" / "reasonix_semgrep_mcp.py")]
    assert MODULE.SERVER_CONFIGS["semgrep"].package_spec == "semgrep==1.135.0"
    assert MODULE.SERVER_CONFIGS["semgrep"].extra_package_specs == ("mcp==1.12.2", "setuptools<81")


def test_probe_process_reports_running_when_child_survives(monkeypatch, tmp_path):
    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stderr = None
            self.terminated = False

        def wait(self, timeout):
            raise MODULE.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

        def terminate(self):
            self.terminated = True

    fake_process = FakeProcess()
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *args, **kwargs: fake_process)

    payload = MODULE.probe_process(["fake"], cwd=tmp_path, env={}, seconds=0.1)

    assert payload["status"] == "running"
    assert payload["returncode"] is None
    assert payload["stderr"] == ""
    assert fake_process.terminated is True


def test_probe_process_reports_exit_and_stderr(monkeypatch, tmp_path):
    class FakeStderr:
        def read(self):
            return "semgrep missing"

    class FakeProcess:
        def __init__(self):
            self.returncode = 3
            self.stderr = FakeStderr()

        def wait(self, timeout):
            return 3

        def terminate(self):
            raise AssertionError("terminate should not be called")

    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    payload = MODULE.probe_process(["fake"], cwd=tmp_path, env={}, seconds=0.1)

    assert payload == {
        "status": "exited",
        "returncode": 3,
        "stderr": "semgrep missing",
    }


def test_reasonix_toml_routes_missing_python_plugins_through_launcher():
    config_path = Path(__file__).resolve().parents[2] / "reasonix.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    plugins = {plugin["name"]: plugin for plugin in config["plugins"]}

    launcher_plugins = {"serena", "postgres", "semgrep", "redis"}
    expected_script = str(MODULE_PATH)

    for name in launcher_plugins:
        plugin = plugins[name]
        assert plugin["command"] == "python"
        assert plugin["args"][0] == expected_script
        assert plugin["args"][1] == name
