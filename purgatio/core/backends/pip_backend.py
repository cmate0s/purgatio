"""Backend de pip: paquetes instalados con ``pip install --user``."""

from __future__ import annotations

import json
import sys
import sysconfig
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture
from .base import Backend

PIP = [sys.executable or "python3", "-m", "pip"]


def parse_pip_json(text: str) -> list[dict[str, str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("pip devolvió una salida que no es JSON")
    return [row for row in data if isinstance(row, dict) and row.get("name")]


def externally_managed() -> bool:
    """PEP 668: la distro marca su Python como gestionado por apt."""
    stdlib = sysconfig.get_path("stdlib") or ""
    return bool(stdlib) and (Path(stdlib) / "EXTERNALLY-MANAGED").exists()


class PipBackend(Backend):
    source = SOURCE_MAP["pip"]

    def available(self) -> bool:
        return run_capture([*PIP, "--version"], timeout=20).returncode == 0

    def list_packages(self) -> list[Package]:
        everything = run_capture([*PIP, "list", "--user", "--format=json"], timeout=60)
        if everything.returncode != 0:
            raise RuntimeError(everything.stderr.strip() or "pip list falló")
        leaves = run_capture([*PIP, "list", "--user", "--not-required", "--format=json"], timeout=60)
        top_level = (
            {row["name"].casefold() for row in parse_pip_json(leaves.stdout)} if leaves.returncode == 0 else None
        )
        packages: list[Package] = []
        for row in parse_pip_json(everything.stdout):
            name = row["name"]
            manual = True if top_level is None else name.casefold() in top_level
            packages.append(
                Package(
                    source="pip",
                    id=name,
                    name=name,
                    version=row.get("version", ""),
                    summary="Paquete Python instalado con pip --user",
                    manual=manual,
                    kind="python" if manual else "dependency",
                )
            )
        packages.sort(key=lambda p: (not p.manual, p.name.casefold()))
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        argv = [*PIP, "uninstall", "-y"]
        if externally_managed():
            argv.append("--break-system-packages")
        argv.append(pkg.id)
        return argv
