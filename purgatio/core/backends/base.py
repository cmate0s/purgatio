"""Contrato común de los backends."""

from __future__ import annotations

from ..models import Orphan, Package, Source


class Backend:
    """Un gestor de software capaz de inventariar y desinstalar."""

    source: Source
    removable: bool = True

    # -- ciclo de vida -------------------------------------------------
    def available(self) -> bool:
        """¿Está el gestor presente en el sistema?"""
        return True

    def list_packages(self) -> list[Package]:
        raise NotImplementedError

    # -- desinstalación ------------------------------------------------
    def removal_argv(self, pkg: Package, purge: bool = False) -> list[str] | None:
        """Orden a ejecutar para desinstalar ``pkg`` (sin prefijo de root)."""
        return None

    def needs_root(self, pkg: Package) -> bool:
        return False

    def supports_purge(self, pkg: Package) -> bool:
        """¿Tiene sentido ofrecer «borrar también configuración/datos»?"""
        return False

    # -- mantenimiento -------------------------------------------------
    def cleanup_items(self) -> list[Orphan]:
        """Restos que se pueden limpiar (huérfanos, revisiones viejas...)."""
        return []
