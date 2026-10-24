"""Modelo de datos común a todas las fuentes de software.

Cada gestor (apt, snap, flatpak, pipx, npm, cargo) o método manual
(AppImage, binario suelto) produce objetos :class:`Package` homogéneos,
de forma que la interfaz no necesita saber nada del gestor subyacente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Source:
    """Una fuente de software (un gestor de paquetes o un método)."""

    id: str
    label: str
    icon: str
    description: str
    order: int

    @property
    def short(self) -> str:
        return self.label.split(" (")[0]


SOURCES: tuple[Source, ...] = (
    Source(
        "apt",
        "APT / deb",
        "system-software-install-symbolic",
        "Paquetes nativos de Debian/Ubuntu, incluidos los .deb instalados a mano.",
        0,
    ),
    Source(
        "snap",
        "Snap",
        "application-x-executable-symbolic",
        "Aplicaciones empaquetadas como snap.",
        1,
    ),
    Source(
        "flatpak",
        "Flatpak",
        "application-x-addon-symbolic",
        "Aplicaciones Flatpak de Flathub u otros remotos.",
        2,
    ),
    Source(
        "pipx",
        "Python (pipx)",
        "utilities-terminal-symbolic",
        "Aplicaciones Python aisladas instaladas con pipx.",
        3,
    ),
    Source(
        "npm",
        "npm global",
        "utilities-terminal-symbolic",
        "Paquetes de Node.js instalados globalmente con npm.",
        4,
    ),
    Source(
        "cargo",
        "Cargo",
        "utilities-terminal-symbolic",
        "Binarios de Rust instalados con «cargo install».",
        5,
    ),
    Source(
        "manual",
        "AppImages y binarios",
        "folder-download-symbolic",
        "AppImages, binarios sueltos y lanzadores que ningún gestor conoce.",
        6,
    ),
)

SOURCE_MAP: dict[str, Source] = {s.id: s for s in SOURCES}
SOURCE_ORDER: dict[str, int] = {s.id: s.order for s in SOURCES}

KIND_LABEL: dict[str, str] = {
    "app": "Aplicación",
    "dependency": "Dependencia",
    "library": "Librería",
    "base": "Componente del sistema",
    "runtime": "Runtime",
    "appimage": "AppImage",
    "binary": "Binario suelto",
    "global": "Paquete global",
}


@dataclass
class Package:
    """Un paquete instalado, venga de donde venga."""

    source: str
    id: str
    name: str
    version: str = ""
    size_bytes: int = 0
    summary: str = ""
    manual: bool = True
    protected: bool = False
    kind: str = "app"
    detail: str = ""
    path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def source_info(self) -> Source:
        return SOURCE_MAP[self.source]

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)

    def matches(self, text: str) -> bool:
        """Búsqueda insensible a mayúsculas sobre nombre, id y descripción."""
        needle = text.casefold().strip()
        if not needle:
            return True
        haystack = " ".join((self.name, self.id, self.summary, self.detail))
        return needle in haystack.casefold()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "size_bytes": self.size_bytes,
            "summary": self.summary,
            "manual": self.manual,
            "protected": self.protected,
            "kind": self.kind,
            "detail": self.detail,
            "path": self.path,
        }


@dataclass
class Orphan:
    """Resto u ítem de mantenimiento que se puede limpiar."""

    source: str
    title: str
    subtitle: str
    argv: list[str]
    needs_root: bool = True
    size_bytes: int = 0
    id: str = ""

    @property
    def source_info(self) -> Source:
        return SOURCE_MAP[self.source]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "size_bytes": self.size_bytes,
            "needs_root": self.needs_root,
        }


def human_size(num_bytes: int) -> str:
    """Tamaño legible con coma decimal (es-ES): «528,5 MB»."""
    if not num_bytes or num_bytes <= 0:
        return "—"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text.replace('.', ',')} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
