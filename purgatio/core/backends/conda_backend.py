"""Backend de conda/mamba: se inventarían los entornos, no cada paquete."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend


def parse_envs(text: str) -> tuple[list[str], str]:
    """``conda env list --json`` → (rutas de entornos, prefijo base)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("conda devolvió una salida que no es JSON")
    envs = [str(p) for p in data.get("envs", [])]
    base = str(data.get("root_prefix") or (envs[0] if envs else ""))
    return envs, base


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


class CondaBackend(Backend):
    source = SOURCE_MAP["conda"]

    def available(self) -> bool:
        return bool(which("conda"))

    def list_packages(self) -> list[Package]:
        proc = run_capture(["conda", "env", "list", "--json"], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "conda env list falló")
        envs, base = parse_envs(proc.stdout)
        packages: list[Package] = []
        for env in envs:
            path = Path(env)
            is_base = env == base
            packages.append(
                Package(
                    source="conda",
                    id=env,
                    name="base" if is_base else path.name,
                    size_bytes=_dir_size(path) if path.is_dir() else 0,
                    summary="Entorno base de conda (no se puede quitar)" if is_base else "Entorno de conda",
                    manual=not is_base,
                    protected=is_base,
                    kind="base" if is_base else "env",
                    detail=env,
                    path=env,
                )
            )
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        if pkg.protected:
            return None
        return ["conda", "env", "remove", "-y", "-p", pkg.id]
