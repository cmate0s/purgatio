"""Backends de paquetes globales: npm y cargo."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend


# Herramientas que Node trae consigo: quitarlas rompe el propio npm.
NPM_PROTECTED = {"npm", "corepack"}


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
                    manual=name not in NPM_PROTECTED,
                    protected=name in NPM_PROTECTED,
                    kind="base" if name in NPM_PROTECTED else "global",
                    detail=f"prefijo global: {self._global_prefix()}",
                )
            )
        packages.sort(key=lambda p: p.name.casefold())
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        if pkg.protected:
            return None
        return ["npm", "uninstall", "-g", pkg.id]

    def needs_root(self, pkg: Package) -> bool:
        return not self._global_prefix().startswith(str(Path.home()))


# «ripgrep v14.1.0:»  o  «foo v0.1.0 (https://github.com/x/y#abc):»  o  «bar v0.2.0 (/ruta):»
CARGO_LINE = re.compile(r"^(?P<name>\S+)\s+v(?P<version>\S+?)(?:\s+\((?P<origin>[^)]*)\))?:$")


def parse_cargo_list(text: str) -> list[dict[str, object]]:
    """Interpreta ``cargo install --list``: crates y los binarios de cada uno."""
    crates: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t":
            match = CARGO_LINE.match(line.strip())
            if match:
                crates.append(
                    {
                        "name": match.group("name"),
                        "version": match.group("version"),
                        "origin": match.group("origin") or "",
                        "bins": [],
                    }
                )
            else:
                crates.append(None)  # type: ignore[arg-type]  # línea de crate no reconocida
        elif crates and crates[-1] is not None:
            crates[-1]["bins"].append(line.strip())  # type: ignore[union-attr]
    return [c for c in crates if c]


class CargoBackend(Backend):
    source = SOURCE_MAP["cargo"]

    def available(self) -> bool:
        return bool(which("cargo"))

    def list_packages(self) -> list[Package]:
        proc = run_capture(["cargo", "install", "--list"], timeout=45)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "cargo install --list falló")
        packages: list[Package] = []
        bin_dir = Path.home() / ".cargo" / "bin"
        for crate in parse_cargo_list(proc.stdout):
            name = str(crate["name"])
            bins = list(crate["bins"])  # type: ignore[call-overload]
            first_bin = bin_dir / (bins[0] if bins else name)
            origin = str(crate["origin"])
            packages.append(
                Package(
                    source="cargo",
                    id=name,
                    name=name,
                    version=str(crate["version"]),
                    summary="Binario de Rust instalado con cargo install" + (f" · desde {origin}" if origin else ""),
                    manual=True,
                    kind="binary",
                    detail=", ".join(bins) if bins else str(first_bin),
                    path=str(first_bin),
                )
            )
        packages.sort(key=lambda p: p.name.casefold())
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        return ["cargo", "uninstall", pkg.id]
