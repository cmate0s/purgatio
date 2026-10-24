"""Detección de software que ningún gestor de paquetes conoce.

Cubre AppImages, binarios sueltos en directorios de usuario y restos
evidentes (por ejemplo copias ``.old`` de binarios).
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from ..models import Package, SOURCE_MAP
from ..runner import run_capture, which
from .base import Backend

OPT = Path("/opt")

HOME = Path.home()
MAX_DEPTH = 3
SKIP_DIRS = {".cache", ".git", "node_modules", ".venv", "__pycache__", "snap"}

# Un enlace que apunta aquí ya lo inventaría otro backend: no es un binario suelto.
MANAGED_ROOTS = tuple(
    str(p)
    for p in (
        HOME / ".local" / "share" / "pipx",
        HOME / ".local" / "pipx",
        HOME / ".cargo",
        HOME / ".nvm",
        HOME / ".volta",
        HOME / "go",
        HOME / ".local" / "lib" / "node_modules",
        Path("/usr/lib"),
        Path("/usr/bin"),
        Path("/usr/share"),
        Path("/snap"),
        Path("/var/lib/snapd"),
        Path("/var/lib/flatpak"),
        Path("/home/linuxbrew"),
    )
)


def is_managed_elsewhere(path: Path) -> bool:
    """¿Es un enlace a algo que ya gestiona pipx, cargo, npm, apt, snap...?"""
    if not path.is_symlink():
        return False
    target = str(path.resolve())
    return any(target == root or target.startswith(root + os.sep) for root in MANAGED_ROOTS)


def _iter_files(root: Path, depth: int) -> list[Path]:
    """Lista ficheros de ``root`` sin bajar de ``depth`` niveles."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    base_depth = len(root.parts)
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        level = len(current_path.parts) - base_depth
        if level >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            found.append(current_path / name)
    return found


def owned_by_dpkg(path: Path) -> bool | None:
    """¿Pertenece ``path`` (o algo dentro) a un paquete? ``None`` si no se puede saber."""
    if not which("dpkg"):
        return None
    for pattern in (str(path), f"{path}/*"):
        proc = run_capture(["dpkg", "-S", pattern], timeout=30)
        if proc.returncode == 0:
            return True
    return False


def _tree_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def opt_directory_removable(path: Path) -> bool:
    """Solo se borra una carpeta de primer nivel de /opt que no sea un enlace."""
    return path.parent == OPT and not path.is_symlink() and path.is_dir()


class ManualBackend(Backend):
    source = SOURCE_MAP["manual"]

    def _appimage_dirs(self) -> list[tuple[Path, int]]:
        return [
            (HOME / "Applications", 2),
            (HOME / "Apps", 2),
            (HOME / "Descargas", 2),
            (HOME / "Downloads", 2),
            (HOME / "Escritorio", 2),
            (HOME / "Desktop", 2),
            (HOME / "opt", 3),
            (Path("/opt"), 2),
        ]

    def _opt_directories(self) -> list[Path]:
        """Carpetas de /opt que dpkg no reconoce (si dpkg no existe, ninguna)."""
        if not OPT.is_dir():
            return []
        found: list[Path] = []
        for child in sorted(OPT.iterdir()):
            if child.is_symlink() or not child.is_dir():
                continue
            if owned_by_dpkg(child) is False:
                found.append(child)
        return found

    def _binary_dirs(self) -> list[Path]:
        return [HOME / ".local" / "bin", HOME / "bin", Path("/usr/local/bin"), Path("/usr/local/sbin")]

    def _desktop_execs(self) -> str:
        """Texto de todos los .desktop de usuario, para detectar integraciones."""
        apps_dir = HOME / ".local" / "share" / "applications"
        chunks: list[str] = []
        for desktop in _iter_files(apps_dir, 1):
            if desktop.suffix != ".desktop":
                continue
            try:
                chunks.append(desktop.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return "\n".join(chunks)

    def list_packages(self) -> list[Package]:
        packages: list[Package] = []
        seen: set[str] = set()
        desktop_text = self._desktop_execs()

        opt_dirs = self._opt_directories()
        for directory in opt_dirs:
            packages.append(
                Package(
                    source="manual",
                    id=str(directory),
                    name=directory.name,
                    size_bytes=_tree_size(directory),
                    summary="Carpeta en /opt que ningún paquete reclama (tarball o instalador a mano)",
                    manual=True,
                    kind="directory",
                    detail=str(directory),
                    path=str(directory),
                )
            )
            seen.add(str(directory))

        for directory, depth in self._appimage_dirs():
            for path in _iter_files(directory, depth):
                if not path.name.lower().endswith(".appimage"):
                    continue
                real = str(path.resolve())
                if real in seen or not path.is_file():
                    continue
                if any(real.startswith(str(d) + os.sep) for d in opt_dirs):
                    continue  # ya cubierta por la carpeta de /opt que la contiene
                seen.add(real)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                integrated = path.name in desktop_text or real in desktop_text
                packages.append(
                    Package(
                        source="manual",
                        id=real,
                        name=path.name,
                        version="",
                        size_bytes=size,
                        summary="AppImage" + (" · integrada en el menú" if integrated else " · sin integrar"),
                        manual=True,
                        kind="appimage",
                        detail=str(path.parent),
                        path=real,
                        extra={"integrated": integrated},
                    )
                )

        for directory in self._binary_dirs():
            for path in _iter_files(directory, 1):
                real = str(path.resolve())
                if directory == Path("/usr/local/bin") and path.is_symlink():
                    target = str(path.resolve())
                    if target.startswith(str(HOME)):
                        real = target
                if real in seen:
                    continue
                if path.name.lower().endswith(".appimage"):
                    continue
                if is_managed_elsewhere(path):
                    continue
                if not path.is_file() and not path.is_symlink():
                    continue
                if not os.access(path, os.X_OK):
                    continue
                seen.add(real)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                leftover = path.name.endswith((".old", ".bak", ".disabled", ".save"))
                summary = "Resto de una instalación anterior" if leftover else f"Binario suelto en {directory}"
                packages.append(
                    Package(
                        source="manual",
                        id=str(path),
                        name=path.name,
                        version="",
                        size_bytes=size,
                        summary=summary,
                        manual=True,
                        kind="binary",
                        detail=str(path),
                        path=str(path),
                        extra={"leftover": leftover},
                    )
                )

        packages.sort(key=lambda p: (p.kind != "appimage", p.name.casefold()))
        return packages

    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        path = Path(pkg.path or pkg.id)
        if pkg.kind == "directory":
            if not opt_directory_removable(path):
                return None
            return ["rm", "-rf", "--", str(path)]
        targets = [path]
        if pkg.kind == "appimage":
            # Retirar también el lanzador del menú, si lo hay.
            apps_dir = HOME / ".local" / "share" / "applications"
            for desktop in _iter_files(apps_dir, 1):
                if desktop.suffix != ".desktop":
                    continue
                try:
                    text = desktop.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if str(path) in text or path.name in text:
                    targets.append(desktop)
        quoted = " ".join(shlex.quote(str(t)) for t in targets)
        return ["/bin/sh", "-c", f"rm -f -- {quoted}"]

    def needs_root(self, pkg: Package) -> bool:
        return not str(Path(pkg.path or pkg.id)).startswith(str(HOME))
