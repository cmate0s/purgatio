"""Backend de APT usando python-apt (sin parsear salidas de consola)."""

from __future__ import annotations

from ..models import Orphan, Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend

APT_GET = which("apt-get") or "/usr/bin/apt-get"


def parse_simulation(output: str, target: str) -> list[str]:
    """Paquetes distintos de ``target`` que ``apt-get -s remove`` eliminaría."""
    names: list[str] = []
    for line in output.splitlines():
        if line.startswith("Remv "):
            name = line.split()[1].split(":")[0]
            if name != target:
                names.append(name)
    return names


class AptBackend(Backend):
    source = SOURCE_MAP["apt"]

    def available(self) -> bool:
        try:
            import apt  # noqa: F401
        except Exception:
            return False
        return True

    def list_packages(self) -> list[Package]:
        import apt
        import apt_pkg

        cache = apt.Cache()
        packages: list[Package] = []
        for pkg in cache:
            try:
                if not pkg.is_installed or pkg.installed is None:
                    continue
                version = pkg.installed
                manual = not pkg.is_auto_installed
                section = version.section or ""
                local = not version.origins
                protected = bool(pkg.essential) or version.priority == apt_pkg.PRI_REQUIRED
                if manual:
                    kind = "app"
                elif protected:
                    kind = "base"
                elif section.startswith(("libs", "libdevel", "python", "perl", "ruby", "golang", "rust", "javascript")):
                    kind = "library"
                else:
                    kind = "dependency"
                detail_bits = [section] if section else []
                if local:
                    detail_bits.append("instalado desde .deb local")
                packages.append(
                    Package(
                        source="apt",
                        id=pkg.name,
                        name=pkg.name,
                        version=version.version,
                        size_bytes=int(version.installed_size or 0),
                        summary=version.summary or "",
                        manual=manual,
                        protected=protected,
                        kind=kind,
                        detail=" · ".join(detail_bits),
                        path=version.filename or "",
                        extra={"architecture": version.architecture, "local": local},
                    )
                )
            except Exception:
                # Un paquete roto no debe tumbar todo el inventario.
                continue
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        if pkg.protected:
            return None
        argv = [APT_GET, "-y", "remove"]
        if purge:
            argv.append("--purge")
        argv.append(pkg.id)
        return argv

    def removal_preview(self, pkg: Package) -> list[str]:
        proc = run_capture([APT_GET, "-s", "remove", pkg.id], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "apt-get -s falló")
        return parse_simulation(proc.stdout, pkg.id)

    def needs_root(self, pkg: Package) -> bool:
        return True

    def supports_purge(self, pkg: Package) -> bool:
        return not pkg.protected

    def cleanup_items(self) -> list[Orphan]:
        import apt

        cache = apt.Cache()
        leftovers = [p for p in cache if p.is_installed and p.is_auto_removable]
        if not leftovers:
            return []
        names = [p.name for p in leftovers]
        preview = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
        total = sum(int(p.installed.installed_size or 0) for p in leftovers if p.installed)
        return [
            Orphan(
                source="apt",
                id="apt-autoremove",
                title=f"{len(names)} paquetes huérfanos",
                subtitle=f"Dependencias que ya no necesita nada: {preview}",
                argv=[APT_GET, "-y", "autoremove", "--purge"],
                needs_root=True,
                size_bytes=total,
            )
        ]
