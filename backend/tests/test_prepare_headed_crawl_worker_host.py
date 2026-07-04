from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_headed_crawl_worker_host.py"
SPEC = importlib.util.spec_from_file_location("prepare_headed_crawl_worker_host", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

HostRuntimePaths = MODULE.HostRuntimePaths
ensure_headed_host_runtime = MODULE.ensure_headed_host_runtime


def test_ensure_headed_host_runtime_recreates_venv_when_base_python_is_missing(tmp_path):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "backend"
    venv_dir = backend_dir / ".host_worker_venv"
    venv_scripts_dir = venv_dir / "Scripts"
    profile_dir = backend_dir / ".host_browser_profiles" / "msedge"
    requirements_file = backend_dir / "requirements-headed-host.txt"
    requirements_marker_file = venv_dir / ".requirements.sha256"
    venv_python = venv_scripts_dir / "python.exe"

    venv_scripts_dir.mkdir(parents=True)
    profile_dir.mkdir(parents=True)
    requirements_file.parent.mkdir(parents=True, exist_ok=True)
    requirements_file.write_text("playwright==1.0\n", encoding="utf-8")
    requirements_marker_file.write_text(MODULE._requirements_hash(requirements_file), encoding="utf-8")
    venv_python.write_text("stale launcher", encoding="utf-8")
    (venv_dir / "pyvenv.cfg").write_text(
        "\n".join(
            [
                "home = C:\\__missing__\\Python311",
                "include-system-site-packages = true",
                "version = 3.11.5",
                "executable = C:\\__missing__\\Python311\\python.exe",
            ]
        ),
        encoding="utf-8",
    )

    paths = HostRuntimePaths(
        repo_root=repo_root,
        backend_dir=backend_dir,
        venv_dir=venv_dir,
        venv_python=venv_python,
        profile_dir=profile_dir,
        requirements_file=requirements_file,
        requirements_marker_file=requirements_marker_file,
    )

    calls: list[list[str]] = []

    def fake_runner(args: list[str], *, cwd: Path) -> None:
        calls.append(args)
        if args[:4] == ["python", "-m", "venv", "--system-site-packages"]:
            venv_scripts_dir.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("fresh launcher", encoding="utf-8")
            (venv_dir / "pyvenv.cfg").write_text(
                "\n".join(
                    [
                        "home = C:\\__missing__\\Python312",
                        "include-system-site-packages = true",
                        "version = 3.12.3",
                        "executable = C:\\__missing__\\Python312\\python.exe",
                    ]
                ),
                encoding="utf-8",
            )

    ensure_headed_host_runtime(
        paths,
        bootstrap_python=["python"],
        command_runner=fake_runner,
    )

    assert calls[0] == ["python", "-m", "venv", "--system-site-packages", str(venv_dir)]
    assert calls[1] == [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        str(requirements_file),
    ]
