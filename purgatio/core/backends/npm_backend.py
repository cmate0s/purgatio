"""Backends de paquetes globales: npm y cargo."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend


class NpmBackend(Backend):
    source = SOURCE_MAP["npm"]

    def __init__(self) -> None:
        self._prefix: str | None = None

    def available(self) -> bool:
        return bool(which("npm"))

    def _global_prefix(self) -> str:
        if self._prefix is None:
            proc = run_capture(["npm", "config", "get", "prefix"], timeout=30)
            self._prefix = proc.stdout.strip() or "/usr"
        return self._prefix

    def list_packages(self) -> list[Package]:
        proc = run_capture(["npm", "ls", "-g", "--depth=0", "--json"], timeout=60)
        text = proc.stdout
        start = text.find("{")
        data: dict = {}
        if start != -1:
            try:
                data = json.loads(text[start:])
            except json.JSONDecodeError:
                data = {}
        packages: list[Package] = []
        for name, info in (data.get("dependencies") or {}).items():
            if not isinstance(info, dict):
                continue
            packages.append(
                Package(
                    source="npm",
                    id=name,
                    name=name,
                    version=str(info.get("version") or ""),
                    summary="Paquete global de Node.js (npm)",
                    manual=True,
                    kind="global",
                    detail=f"prefijo global: {self._global_prefix()}",
                )
            )
        packages.sort(key=lambda p: p.name.casefold())
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        return ["npm", "uninstall", "-g", pkg.id]

    def needs_root(self, pkg: Package) -> bool:
        return not self._global_prefix().startswith(str(Path.home()))


CARGO_LINE = re.compile(r"^(?P<name>\S+)\s+v(?P<version>\S+):$")


class CargoBackend(Backend):
    source = SOURCE_MAP["cargo"]

    def available(self) -> bool:
        return bool(which("cargo"))

    def list_packages(self) -> list[Package]:
        proc = run_capture(["cargo", "install", "--list"], timeout=45)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "cargo install --list falló")
        packages: list[Package] = []
        for line in proc.stdout.splitlines():
            match = CARGO_LINE.match(line.strip())
            if not match:
                continue
            name = match.group("name")
            packages.append(
                Package(
                    source="cargo",
                    id=name,
                    name=name,
                    version=match.group("version"),
                    summary="Binario de Rust instalado con cargo install",
                    manual=True,
                    kind="binary",
                    detail=str(Path.home() / ".cargo" / "bin" / name),
                    path=str(Path.home() / ".cargo" / "bin" / name),
                )
            )
        packages.sort(key=lambda p: p.name.casefold())
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        return ["cargo", "uninstall", pkg.id]
