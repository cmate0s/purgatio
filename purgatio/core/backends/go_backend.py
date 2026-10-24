"""Backend de Go: binarios que ``go install`` deja en GOBIN o ``~/go/bin``."""

from __future__ import annotations

import os
from pathlib import Path

from ..models import Package, SOURCE_MAP
from .base import Backend


def go_bin_dir() -> Path:
    gobin = os.environ.get("GOBIN")
    if gobin:
        return Path(gobin)
    gopath = os.environ.get("GOPATH", "").split(os.pathsep)[0]
    return Path(gopath or Path.home() / "go") / "bin"


class GoBackend(Backend):
    source = SOURCE_MAP["go"]

    def available(self) -> bool:
        return go_bin_dir().is_dir()

    def list_packages(self) -> list[Package]:
        directory = go_bin_dir()
        packages: list[Package] = []
        for path in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
            if not path.is_file() or not os.access(path, os.X_OK):
                continue
            packages.append(
                Package(
                    source="go",
                    id=path.name,
                    name=path.name,
                    size_bytes=path.stat().st_size,
                    summary="Binario de Go instalado con go install",
                    manual=True,
                    kind="binary",
                    detail=str(path),
                    path=str(path),
                )
            )
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        path = Path(pkg.path)
        # Solo se borra un fichero que esté directamente en el directorio de binarios de Go.
        if pkg.protected or path.parent != go_bin_dir():
            return None
        return ["rm", "-f", "--", str(path)]
