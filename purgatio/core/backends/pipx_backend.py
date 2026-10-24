"""Backend de pipx: aplicaciones Python aisladas en su propio venv."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


class PipxBackend(Backend):
    source = SOURCE_MAP["pipx"]

    def available(self) -> bool:
        return bool(which("pipx"))

    def list_packages(self) -> list[Package]:
        proc = run_capture(["pipx", "list", "--json"], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "pipx list falló")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("pipx devolvió una salida que no es JSON")
        packages: list[Package] = []
        for name, info in (data.get("venvs") or {}).items():
            meta = (info.get("metadata") or {}).get("main_package") or {}
            env_path = Path(info.get("environment") or "")
            apps = meta.get("apps") or []
            packages.append(
                Package(
                    source="pipx",
                    id=name,
                    name=meta.get("package_name") or name,
                    version=meta.get("package_version") or "",
                    size_bytes=_dir_size(env_path) if env_path.exists() else 0,
                    summary="Aplicación Python aislada (pipx)",
                    manual=True,
                    kind="app",
                    detail=("órdenes: " + ", ".join(apps)) if apps else "",
                    path=str(env_path),
                )
            )
        packages.sort(key=lambda p: p.name.casefold())
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        return ["pipx", "uninstall", pkg.id]
