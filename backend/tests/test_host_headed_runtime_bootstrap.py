from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.prepare_headed_crawl_worker_host import (
    _CLEARED_ENV_KEYS,
    ensure_headed_host_runtime,
    _venv_uses_system_site_packages,
    resolve_runtime_paths,
)


def _write_requirements(path: Path, content: str = "fastapi==0.1.0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_pyvenv_cfg(venv_dir: Path, *, include_system_site_packages: bool) -> None:
    venv_dir.mkdir(parents=True, exist_ok=True)
    (venv_dir / "pyvenv.cfg").write_text(
        "home = C:\\Python311\n"
        f"include-system-site-packages = {'true' if include_system_site_packages else 'false'}\n",
        encoding="utf-8",
    )


def test_ensure_headed_host_runtime_creates_profile_and_venv_and_installs_requirements():
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_root = Path(temp_dir) / "repo"
        paths = resolve_runtime_paths(repo_root)
        _write_requirements(paths.requirements_file)
        calls: list[tuple[list[str], Path]] = []

        def runner(args: list[str], *, cwd: Path) -> None:
            calls.append((args, cwd))
            if args[1:3] == ["-m", "venv"]:
                paths.venv_python.parent.mkdir(parents=True, exist_ok=True)
                paths.venv_python.write_text("", encoding="utf-8")

        ensure_headed_host_runtime(paths, bootstrap_python=["python"], command_runner=runner)

        assert paths.profile_dir.exists()
        assert paths.venv_python.exists()
        assert paths.requirements_marker_file.exists()
        assert calls[0][0] == ["python", "-m", "venv", "--system-site-packages", str(paths.venv_dir)]
        assert Path(calls[0][1]).resolve() == repo_root.resolve()
        assert calls[1][0] == [
            str(paths.venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(paths.requirements_file),
        ]
        assert Path(calls[1][1]).resolve() == paths.backend_dir.resolve()


def test_ensure_headed_host_runtime_skips_install_when_marker_matches():
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_root = Path(temp_dir) / "repo"
        paths = resolve_runtime_paths(repo_root)
        _write_requirements(paths.requirements_file)
        paths.profile_dir.mkdir(parents=True, exist_ok=True)
        _write_pyvenv_cfg(paths.venv_dir, include_system_site_packages=True)
        paths.venv_python.parent.mkdir(parents=True, exist_ok=True)
        paths.venv_python.write_text("", encoding="utf-8")
        expected_hash = hashlib.sha256(paths.requirements_file.read_bytes()).hexdigest()
        paths.requirements_marker_file.write_text(expected_hash, encoding="utf-8")
        calls: list[tuple[list[str], Path]] = []

        ensure_headed_host_runtime(
            paths,
            bootstrap_python=["python"],
            command_runner=lambda args, *, cwd: calls.append((args, cwd)),
        )

        assert calls == []


def test_ensure_headed_host_runtime_reinstalls_when_marker_is_stale():
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_root = Path(temp_dir) / "repo"
        paths = resolve_runtime_paths(repo_root)
        _write_requirements(paths.requirements_file, "fastapi==0.2.0\n")
        paths.profile_dir.mkdir(parents=True, exist_ok=True)
        _write_pyvenv_cfg(paths.venv_dir, include_system_site_packages=True)
        paths.venv_python.parent.mkdir(parents=True, exist_ok=True)
        paths.venv_python.write_text("", encoding="utf-8")
        paths.requirements_marker_file.write_text("stale", encoding="utf-8")
        calls: list[tuple[list[str], Path]] = []

        ensure_headed_host_runtime(
            paths,
            bootstrap_python=["python"],
            command_runner=lambda args, *, cwd: calls.append((args, cwd)),
        )

        assert calls == [
            (
                [
                    str(paths.venv_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-r",
                    str(paths.requirements_file),
                ],
                paths.backend_dir,
            ),
        ]


def test_venv_uses_system_site_packages_detects_bootstrap_setting():
    with tempfile.TemporaryDirectory() as temp_dir:
        venv_dir = Path(temp_dir) / "venv"
        _write_pyvenv_cfg(venv_dir, include_system_site_packages=True)

        assert _venv_uses_system_site_packages(venv_dir) is True


def test_cleared_env_keys_cover_proxy_and_no_index_blockers():
    assert "PIP_NO_INDEX" in _CLEARED_ENV_KEYS
    assert "HTTP_PROXY" in _CLEARED_ENV_KEYS
    assert "HTTPS_PROXY" in _CLEARED_ENV_KEYS
    assert "ALL_PROXY" in _CLEARED_ENV_KEYS
