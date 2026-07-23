#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CommandRunner = Callable[[list[str]], None]
_CLEARED_ENV_KEYS = (
    "PIP_NO_INDEX",
    "PIP_FIND_LINKS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
)


@dataclass(frozen=True)
class HostRuntimePaths:
    repo_root: Path
    backend_dir: Path
    venv_dir: Path
    venv_python: Path
    profile_dir: Path
    requirements_file: Path
    requirements_marker_file: Path


def resolve_runtime_paths(
    repo_root: str | Path | None = None,
    *,
    browser_channel: str | None = None,
) -> HostRuntimePaths:
    browser_channel = (
        browser_channel
        or os.environ.get("JOBSDB_HEADED_BROWSER_CHANNEL")
        or "msedge"
    ).strip() or "msedge"
    resolved_repo_root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    backend_dir = resolved_repo_root / "backend"
    venv_dir = backend_dir / ".host_worker_venv"
    venv_bin_dir = "Scripts" if os.name == "nt" else "bin"
    venv_python_name = "python.exe" if os.name == "nt" else "python"
    return HostRuntimePaths(
        repo_root=resolved_repo_root,
        backend_dir=backend_dir,
        venv_dir=venv_dir,
        venv_python=venv_dir / venv_bin_dir / venv_python_name,
        profile_dir=backend_dir / ".host_browser_profiles" / browser_channel,
        requirements_file=backend_dir / "requirements-headed-host.txt",
        requirements_marker_file=venv_dir / ".requirements.sha256",
    )


def _run_subprocess(args: list[str], *, cwd: Path) -> None:
    env = dict(os.environ)
    for key in _CLEARED_ENV_KEYS:
        env.pop(key, None)
    subprocess.run(args, cwd=str(cwd), check=True, env=env)


def _requirements_hash(requirements_file: Path) -> str:
    return hashlib.sha256(requirements_file.read_bytes()).hexdigest()


def _venv_uses_system_site_packages(venv_dir: Path) -> bool:
    config_path = venv_dir / "pyvenv.cfg"
    if not config_path.exists():
        return False
    content = config_path.read_text(encoding="utf-8").lower()
    return "include-system-site-packages = true" in content


def _read_pyvenv_cfg(venv_dir: Path) -> dict[str, str]:
    config_path = venv_dir / "pyvenv.cfg"
    if not config_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def _venv_base_interpreter_exists(venv_dir: Path) -> bool:
    config = _read_pyvenv_cfg(venv_dir)

    executable = config.get("executable")
    if executable:
        return Path(executable).exists()

    home = config.get("home")
    if not home:
        return False

    home_path = Path(home)
    return any(
        (home_path / candidate).exists()
        for candidate in ("python.exe", "python3", "python")
    )


def ensure_headed_host_runtime(
    paths: HostRuntimePaths,
    *,
    bootstrap_python: list[str] | None = None,
    command_runner: Callable[..., None] | None = None,
) -> HostRuntimePaths:
    bootstrap_python = list(bootstrap_python or [sys.executable])
    command_runner = command_runner or _run_subprocess

    paths.profile_dir.mkdir(parents=True, exist_ok=True)

    if paths.venv_dir.exists() and (
        not _venv_uses_system_site_packages(paths.venv_dir)
        or not _venv_base_interpreter_exists(paths.venv_dir)
    ):
        shutil.rmtree(paths.venv_dir)

    if not paths.venv_python.exists():
        command_runner(
            [*bootstrap_python, "-m", "venv", "--system-site-packages", str(paths.venv_dir)],
            cwd=paths.repo_root,
        )

    expected_hash = _requirements_hash(paths.requirements_file)
    current_hash = (
        paths.requirements_marker_file.read_text(encoding="utf-8").strip()
        if paths.requirements_marker_file.exists()
        else ""
    )
    if current_hash != expected_hash:
        command_runner(
            [
                str(paths.venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(paths.requirements_file),
            ],
            cwd=paths.backend_dir,
        )
        paths.requirements_marker_file.parent.mkdir(parents=True, exist_ok=True)
        paths.requirements_marker_file.write_text(expected_hash, encoding="utf-8")

    return paths


def main() -> int:
    paths = resolve_runtime_paths()
    ensure_headed_host_runtime(paths)
    print(f"HOST_VENV={paths.venv_python}")
    print(f"HOST_PROFILE={paths.profile_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
