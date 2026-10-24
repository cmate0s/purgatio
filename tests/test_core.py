"""Pruebas del núcleo de Purgatio (sin interfaz).

    python3 tests/test_core.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from purgatio.core.backends.apt_backend import AptBackend, parse_simulation  # noqa: E402
from purgatio.core.backends.brew_backend import parse_brew_versions  # noqa: E402
from purgatio.core.backends.npm_backend import NpmBackend, parse_cargo_list  # noqa: E402
from purgatio.core.backends.snap_backend import PROTECTED_RE, parse_snap_table  # noqa: E402
from purgatio.core.backends.manual_backend import ManualBackend, is_managed_elsewhere, opt_directory_removable  # noqa: E402
from purgatio.core.backends.flatpak_backend import FlatpakBackend, disambiguate, parse_unused  # noqa: E402
from purgatio.core.backends.pip_backend import PipBackend, parse_pip_json  # noqa: E402
from purgatio.core.backends.conda_backend import CondaBackend, parse_envs  # noqa: E402
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


def test_apt_simulation() -> None:
    sample = """Reading package lists...
The following packages will be REMOVED:
  foo ubuntu-desktop
Remv foo [1.0]
Remv ubuntu-desktop:amd64 [1.1]
Remv libfoo1 [1.0]
"""
    check(parse_simulation(sample, "foo") == ["ubuntu-desktop", "libfoo1"], "arrastre sin el objetivo ni la arquitectura")
    check(parse_simulation("Remv foo [1.0]", "foo") == [], "sin arrastre")


def test_cargo_parse() -> None:
    sample = """ripgrep v14.1.0:
    rg
foo v0.1.0 (https://github.com/x/y#abc123):
    foo-cli
    foo-daemon
bar v0.2.0 (/home/u/src/bar):
    bar
"""
    crates = parse_cargo_list(sample)
    check([c["name"] for c in crates] == ["ripgrep", "foo", "bar"], "incluye crates de git y de ruta local")
    check(crates[0]["bins"] == ["rg"], "binario distinto del nombre del crate")
    check(crates[1]["origin"] == "https://github.com/x/y#abc123", "origen de git")
    check(crates[1]["bins"] == ["foo-cli", "foo-daemon"], "varios binarios")


def test_snap_parse_and_protection() -> None:
    sample = """Name               Version     Rev    Tracking       Publisher   Notes
core22             20240111    1380   latest/stable  canonical✓  base
gnome-42-2204      0+git.ff35a853  176  latest/stable  canonical✓  -
gnome-text-editor  46.0        200    latest/stable  canonical✓  -
firefox            130.0       4650   latest/stable  mozilla✓    -
"""
    rows = parse_snap_table(sample)
    check([r[0] for r in rows] == ["core22", "gnome-42-2204", "gnome-text-editor", "firefox"], "cuatro filas")
    check(PROTECTED_RE.match("core22") and PROTECTED_RE.match("gnome-42-2204"), "bases protegidas")
    check(not PROTECTED_RE.match("gnome-text-editor"), "una app de GNOME no es un runtime")
    check(not PROTECTED_RE.match("core-keeper"), "prefijo core- no basta")


def test_npm_guardrails() -> None:
    backend = NpmBackend()
    check(backend.removal_argv(Package(source="npm", id="npm", name="npm", protected=True)) is None, "npm no se quita a sí mismo")
    argv = backend.removal_argv(Package(source="npm", id="typescript", name="typescript"))
    check(argv == ["npm", "uninstall", "-g", "typescript"], "comando de npm")


def test_brew_parse() -> None:
    check(parse_brew_versions("git 2.45.0\nopenssl@3 3.3.0 3.2.1\n") == {"git": "2.45.0", "openssl@3": "3.2.1"}, "última versión")


def test_managed_symlinks(tmp: Path | None = None) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        link = Path(raw) / "tool"
        link.symlink_to("/usr/bin/env")
        check(is_managed_elsewhere(link), "enlace a /usr/bin lo gestiona apt")
        plain = Path(raw) / "script"
        plain.write_text("#!/bin/sh\n")
        check(not is_managed_elsewhere(plain), "un fichero normal es un binario suelto")


def test_flatpak_unused_and_ids() -> None:
    listed = """Looking for unused runtimes...

        ID                                   Branch   Op
 1.     org.freedesktop.Platform.GL.default  23.08    r
 2.     org.gnome.Platform                   45       r

"""
    check(parse_unused(listed) == ["org.freedesktop.Platform.GL.default//23.08", "org.gnome.Platform//45"], "refs sobrantes")
    check(parse_unused("Nothing unused to uninstall") == [], "nada que limpiar")
    check(parse_unused("error: unknown option") is None, "salida ilegible: se sigue ofreciendo")
    both = [
        Package(source="flatpak", id="org.x.App", name="App", extra={"installation": "user"}),
        Package(source="flatpak", id="org.x.App", name="App", extra={"installation": "system"}),
        Package(source="flatpak", id="org.y.Solo", name="Solo", extra={"installation": "user"}),
    ]
    disambiguate(both)
    check([p.id for p in both] == ["org.x.App@user", "org.x.App@system", "org.y.Solo"], "ids únicos solo si chocan")
    argv = FlatpakBackend().removal_argv(both[1])
    check(argv is not None and argv[-1] == "org.x.App" and "--system" in argv, "se desinstala con el id real")


def test_pip_and_conda() -> None:
    rows = parse_pip_json('[{"name": "black", "version": "24.1"}, {"name": "click", "version": "8.1"}]')
    check([r["name"] for r in rows] == ["black", "click"], "filas de pip")
    argv = PipBackend().removal_argv(Package(source="pip", id="black", name="black"))
    check(argv is not None and argv[-1] == "black" and "uninstall" in argv, "comando de pip")
    envs, base = parse_envs('{"envs": ["/home/u/miniconda3", "/home/u/miniconda3/envs/ds"], "root_prefix": "/home/u/miniconda3"}')
    check(envs[1].endswith("/ds") and base == "/home/u/miniconda3", "entornos y base")
    backend = CondaBackend()
    check(backend.removal_argv(Package(source="conda", id=base, name="base", protected=True)) is None, "el entorno base no se quita")
    check(backend.removal_argv(Package(source="conda", id=envs[1], name="ds"))[-2:] == ["-p", envs[1]], "se quita por ruta")


def test_opt_guard() -> None:
    check(not opt_directory_removable(Path("/opt/foo/bar")), "solo primer nivel de /opt")
    check(not opt_directory_removable(Path("/opt")), "nunca /opt entero")
    check(not opt_directory_removable(Path("/etc")), "nunca fuera de /opt")
    backend = ManualBackend()
    bad = Package(source="manual", id="/etc", name="etc", kind="directory", path="/etc")
    check(backend.removal_argv(bad) is None, "un directorio fuera de /opt no genera comando")


def test_scan() -> None:
    if not AptBackend().available():
        print("  --  test_scan omitido: python-apt no está disponible")
        return
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
        test_apt_simulation,
        test_cargo_parse,
        test_snap_parse_and_protection,
        test_npm_guardrails,
        test_brew_parse,
        test_managed_symlinks,
        test_flatpak_unused_and_ids,
        test_pip_and_conda,
        test_opt_guard,
        test_inventory,
        test_scan,
    ):
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{checks} comprobaciones correctas.")
