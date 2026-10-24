"""Backend de Homebrew (Linuxbrew)."""

from __future__ import annotations

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend


def parse_brew_versions(text: str) -> dict[str, str]:
    """``brew list --versions`` → {fórmula: última versión}."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            result[parts[0]] = parts[-1]
    return result


class BrewBackend(Backend):
    source = SOURCE_MAP["brew"]

    def available(self) -> bool:
        return bool(which("brew"))

    def list_packages(self) -> list[Package]:
        listed = run_capture(["brew", "list", "--formula", "--versions"], timeout=90)
        if listed.returncode != 0:
            raise RuntimeError(listed.stderr.strip() or "brew list falló")
        leaves = run_capture(["brew", "leaves"], timeout=90)
        leaf_names = set(leaves.stdout.split()) if leaves.returncode == 0 else None
        packages: list[Package] = []
        for name, version in sorted(parse_brew_versions(listed.stdout).items()):
            manual = True if leaf_names is None else name in leaf_names
            packages.append(
                Package(
                    source="brew",
                    id=name,
                    name=name,
                    version=version,
                    summary="Fórmula de Homebrew",
                    manual=manual,
                    kind="app" if manual else "dependency",
                )
            )
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        return ["brew", "uninstall", pkg.id]
