"""Backend de Flatpak."""

from __future__ import annotations

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
        argv.append(pkg.id)
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
            items.append(
                Orphan(
                    source="flatpak",
                    id=f"flatpak-unused-{installation}",
                    title=f"Runtimes no utilizados ({installation})",
                    subtitle="Flatpak calcula qué runtimes y extensiones ya no necesita ninguna app",
                    argv=[FLATPAK, "uninstall", "-y", f"--{installation}", "--unused"],
                    needs_root=installation == "system",
                )
            )
        return items
