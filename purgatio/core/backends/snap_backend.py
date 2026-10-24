"""Backend de Snap (snapd no ofrece JSON: se parsea su tabla estable)."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Orphan, Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend

SNAP = which("snap") or "/usr/bin/snap"
SNAPS_DIR = Path("/var/lib/snapd/snaps")

# Componentes que sostienen el propio sistema de snaps (bases, runtimes y
# plataformas de temas): no se ofrecen para quitar. Se compara por patrón exacto
# para no ocultar apps reales como «gnome-text-editor».
PROTECTED_RE = re.compile(
    r"^(snapd|bare|core\d*|gtk-common-themes"
    r"|gnome-\d+-\d+(-\d+)?(-sdk)?"
    r"|mesa-[\w.-]+|kf[56]-[\w.-]+|kde-frameworks-[\w.-]+)$"
)
COLUMNS = re.compile(r"\s{2,}")


def parse_snap_table(text: str) -> list[list[str]]:
    """Filas (nombre, versión, rev, canal, editor, notas) de ``snap list``."""
    rows: list[list[str]] = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        fields = COLUMNS.split(line.strip())
        if len(fields) < 6:
            fields = line.split(maxsplit=5)
        if len(fields) >= 6:
            rows.append(fields[:6])
    return rows


def _snap_rows(extra: list[str] | None = None) -> list[list[str]]:
    proc = run_capture([SNAP, "list", *(extra or [])], timeout=45)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "snap list falló")
    return parse_snap_table(proc.stdout)


def _revision_size(name: str, rev: str) -> int:
    candidate = SNAPS_DIR / f"{name}_{rev}.snap"
    try:
        return candidate.stat().st_size
    except OSError:
        return 0


class SnapBackend(Backend):
    source = SOURCE_MAP["snap"]

    def available(self) -> bool:
        return bool(which("snap"))

    def list_packages(self) -> list[Package]:
        packages: list[Package] = []
        for name, version, rev, tracking, publisher, notes in _snap_rows():
            is_base = "base" in notes.split() or bool(PROTECTED_RE.match(name))
            packages.append(
                Package(
                    source="snap",
                    id=name,
                    name=name,
                    version=version,
                    size_bytes=_revision_size(name, rev),
                    summary=f"Snap · canal {tracking} · {publisher}",
                    manual=not is_base,
                    protected=is_base,
                    kind="base" if is_base else "app",
                    detail=f"revisión {rev}" + (f" · {notes}" if notes not in ("-", "") else ""),
                    extra={"revision": rev, "publisher": publisher, "tracking": tracking},
                )
            )
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        if pkg.protected:
            return None
        argv = [SNAP, "remove", pkg.id]
        if purge:
            argv.append("--purge")
        return argv

    def needs_root(self, pkg: Package) -> bool:
        return True

    def supports_purge(self, pkg: Package) -> bool:
        return not pkg.protected

    def cleanup_items(self) -> list[Orphan]:
        items: list[Orphan] = []
        for name, version, rev, _tracking, _publisher, notes in _snap_rows(["--all"]):
            if notes.strip() != "disabled":
                continue
            items.append(
                Orphan(
                    source="snap",
                    id=f"{name}@{rev}",
                    title=f"{name} · revisión {rev}",
                    subtitle=f"Revisión antigua de la versión {version} que ya no está activa",
                    argv=[SNAP, "remove", name, f"--revision={rev}"],
                    needs_root=True,
                    size_bytes=_revision_size(name, rev),
                )
            )
        items.sort(key=lambda o: o.size_bytes, reverse=True)
        return items
