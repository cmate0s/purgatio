"""Pruebas del núcleo de Purgatio (sin interfaz).

    python3 tests/test_core.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from purgatio.core.backends.apt_backend import AptBackend  # noqa: E402
from purgatio.core.backends.flatpak_backend import parse_size  # noqa: E402
from purgatio.core.history import parse_history  # noqa: E402
from purgatio.core.inventory import render_markdown  # noqa: E402
from purgatio.core.models import Package, human_size  # noqa: E402
from purgatio.core.registry import ScanResult, scan_sync  # noqa: E402

checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def test_sizes() -> None:
    check(human_size(0) == "—", "0 bytes debe ser un guion")
    check(human_size(512) == "512 B", "bytes sin decimales")
    check(human_size(1536) == "1,5 KB", "coma decimal y unidad")
    check(human_size(630_374_400) == "601,2 MB", "tamaño de claude-desktop")
    check(parse_size("528.5 MB") == 528_500_000, "tamaño de flatpak")
    check(parse_size("1,5 GB") == 1_500_000_000, "tamaño con coma")
    check(parse_size("—") == 0, "tamaño desconocido")


def test_history() -> None:
    sample = """Start-Date: 2026-08-26  05:40:07
Commandline: apt install steam-installer
Install: steam-installer:amd64 (1:1.0.0.79~ubuntu1, automatic), steam-libs-amd64:amd64 (1:1.0.0.79~ubuntu1)
End-Date: 2026-08-26  05:41:10

Start-Date: 2026-10-22  18:59:00
Commandline: apt upgrade
Upgrade: libc6:amd64 (2.43-2ubuntu2.2, 2.43-2ubuntu2.3)
End-Date: 2026-10-22  19:01:00
"""
    entries = parse_history(sample)
    check(len(entries) == 2, "dos transacciones")
    install = [e for e in entries if e.action == "install"][0]
    check(install.packages == ["steam-installer", "steam-libs-amd64"], "nombres sin arquitectura")
    check(install.automatic == 1, "marca de automático")
    check(install.date is not None and install.date.year == 2026, "fecha interpretada")
    check(entries[0].date >= entries[1].date, "orden descendente")


def test_matching() -> None:
    pkg = Package(source="apt", id="qbittorrent", name="qBittorrent", summary="Cliente BitTorrent")
    check(pkg.matches("bittorrent"), "búsqueda sin distinguir mayúsculas")
    check(pkg.matches("cliente"), "búsqueda en la descripción")
    check(not pkg.matches("vlc"), "no debe coincidir con otra app")
    check(pkg.key == "apt:qbittorrent", "clave única")


def test_apt_guardrails() -> None:
    backend = AptBackend()
    protected = Package(source="apt", id="libc6", name="libc6", protected=True)
    check(backend.removal_argv(protected) is None, "no se ofrece quitar componentes protegidos")
    normal = Package(source="apt", id="htop", name="htop")
    argv = backend.removal_argv(normal, purge=True)
    check(argv is not None and argv[-2] == "--purge" and argv[-1] == "htop", "comando de purga correcto")


def test_inventory() -> None:
    result = ScanResult(
        packages=[
            Package(source="apt", id="htop", name="htop", version="3.4", size_bytes=2_000_000, manual=True),
            Package(source="apt", id="libc6", name="libc6", version="2.43", size_bytes=99_000_000, manual=False),
        ]
    )
    text = render_markdown(result)
    check("**htop**" in text and "**libc6**" not in text, "las dependencias no se listan por defecto")
    full = render_markdown(result, include_dependencies=True)
    check("**libc6**" in full, "modo completo incluye dependencias")


def test_scan() -> None:
    result = scan_sync(include_orphans=False)
    check(len(result.packages) > 10, "el escaneo real devuelve paquetes")
    check(any(p.source == "apt" for p in result.packages), "APT presente en este equipo")
    check(all(p.name for p in result.packages), "todos los paquetes tienen nombre")


if __name__ == "__main__":
    for test in (
        test_sizes,
        test_history,
        test_matching,
        test_apt_guardrails,
        test_inventory,
        test_scan,
    ):
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{checks} comprobaciones correctas.")
