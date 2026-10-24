"""Backend de Flatpak."""

from __future__ import annotations

import re

from ..models import Orphan, Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend

FLATPAK = which("flatpak") or "/usr/bin/flatpak"
UNITS = {"B": 1, "bytes": 1, "kB": 1000, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}


def parse_size(text: str) -> int:
    """Convierte «528.5 MB» (o «528,5 MB») en bytes."""
    text = (text or "").strip().replace(",", ".")
    if not text or text == "-":
        return 0
    parts = text.split()
    try:
        value = float(parts[0])
    except (ValueError, IndexError):
        return 0
    unit = parts[1] if len(parts) > 1 else "B"
    return int(value * UNITS.get(unit, 1))


UNUSED_ROW = re.compile(r"^\s*\d+\.\s+(?P<ref>\S+)\s+(?P<branch>\S+)\s+[a-z]\b")


def parse_unused(output: str) -> list[str] | None:
    """Refs que ``flatpak uninstall --unused --assumeno`` propone quitar.

    Devuelve ``[]`` si no hay nada y ``None`` si la salida no se entiende
    (en ese caso es más seguro seguir ofreciendo la limpieza).
    """
    refs = [f"{m['ref']}//{m['branch']}" for line in output.splitlines() if (m := UNUSED_ROW.match(line))]
    if refs:
        return refs
    lowered = output.lower()
    if "nothing unused" in lowered or "nothing to do" in lowered:
        return []
    return None


def disambiguate(packages: list[Package]) -> None:
    """Si una app está en las instalaciones ``user`` y ``system``, da ids únicos."""
    counts: dict[str, int] = {}
    for pkg in packages:
        counts[pkg.id] = counts.get(pkg.id, 0) + 1
    for pkg in packages:
        pkg.extra.setdefault("app_id", pkg.id)
        if counts[pkg.id] > 1:
            pkg.id = f"{pkg.id}@{pkg.extra.get('installation', '')}"


class FlatpakBackend(Backend):
    source = SOURCE_MAP["flatpak"]

    def available(self) -> bool:
        return bool(which("flatpak"))

    def list_packages(self) -> list[Package]:
        proc = run_capture(
            [
                FLATPAK,
                "list",
                "--app",
                "--columns=application,name,version,origin,size,installation",
            ],
            timeout=45,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "flatpak list falló")
        packages: list[Package] = []
        for line in proc.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 6:
                continue
            app_id, name, version, origin, size, installation = fields[:6]
            packages.append(
                Package(
                    source="flatpak",
                    id=app_id,
                    name=name or app_id,
                    version=version,
                    size_bytes=parse_size(size),
                    summary=f"Flatpak · {origin} · instalación {installation}",
                    manual=True,
                    kind="app",
                    detail=f"{app_id} · {installation}",
                    extra={"installation": installation, "origin": origin},
                )
            )
        disambiguate(packages)
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        if pkg.protected:
            return None
        argv = [FLATPAK, "uninstall", "-y"]
        installation = pkg.extra.get("installation")
        if installation in ("system", "user"):
            argv.append(f"--{installation}")
        if purge:
            argv.append("--delete-data")
        argv.append(str(pkg.extra.get("app_id", pkg.id)))
        return argv

    def needs_root(self, pkg: Package) -> bool:
        return pkg.extra.get("installation") == "system"

    def supports_purge(self, pkg: Package) -> bool:
        return True

    def cleanup_items(self) -> list[Orphan]:
        proc = run_capture(
            [FLATPAK, "list", "--runtime", "--columns=application,size,installation"],
            timeout=45,
        )
        if proc.returncode != 0:
            return []
        installations = {row.split("\t")[2] for row in proc.stdout.splitlines() if len(row.split("\t")) >= 3}
        items: list[Orphan] = []
        for installation in sorted(installations):
            # --assumeno: Flatpak enseña qué quitaría y responde «no» por nosotros.
            preview = run_capture(
                [FLATPAK, "uninstall", "--unused", "--assumeno", f"--{installation}"], timeout=60
            )
            unused = parse_unused(preview.stdout + preview.stderr)
            if unused == []:
                continue
            subtitle = (
                f"{len(unused)} runtime(s) o extensión(es) que ninguna app necesita"
                if unused
                else "Flatpak calcula qué runtimes y extensiones ya no necesita ninguna app"
            )
            items.append(
                Orphan(
                    source="flatpak",
                    id=f"flatpak-unused-{installation}",
                    title=f"Runtimes no utilizados ({installation})",
                    subtitle=subtitle,
                    argv=[FLATPAK, "uninstall", "-y", f"--{installation}", "--unused"],
                    needs_root=installation == "system",
                )
            )
        return items
