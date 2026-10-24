"""Interfaz de línea de órdenes de Purgatio.

Existe por dos motivos: depurar el motor sin abrir ventanas y ofrecer una
alternativa scriptable (exportar el inventario, listar, desinstalar).

    purgatio list --source apt --all
    purgatio export --out inventario.md
    purgatio history --limit 20
    purgatio orphans
    purgatio remove flatpak:com.obsproject.Studio --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import inventory
from .core.history import load_history
from .core.models import SOURCE_MAP, Package, human_size
from .core.registry import BACKENDS, get_backend, scan_sync
from .core.runner import display_command, run_streaming, with_root

COMMANDS = {"list", "export", "history", "orphans", "remove", "info"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="purgatio", description="Inventario y desinstalación unificada de software.")
    parser.add_argument("--version", action="version", version=f"Purgatio {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    lst = sub.add_parser("list", help="Lista el software instalado")
    lst.add_argument("--source", choices=[b.source.id for b in BACKENDS])
    lst.add_argument("--all", action="store_true", help="Incluye dependencias y librerías")
    lst.add_argument("--search")
    lst.add_argument("--json", action="store_true")
    lst.add_argument("--limit", type=int, default=0)

    exp = sub.add_parser("export", help="Exporta el inventario completo")
    exp.add_argument("--format", choices=["md", "json"], default="md")
    exp.add_argument("--out", help="Fichero de destino ('-' para stdout)")
    exp.add_argument("--all", action="store_true")

    hist = sub.add_parser("history", help="Historial de instalaciones de APT")
    hist.add_argument("--limit", type=int, default=25)

    sub.add_parser("orphans", help="Restos que se pueden limpiar")

    rem = sub.add_parser("remove", help="Desinstala source:id (por ejemplo apt:htop)")
    rem.add_argument("target")
    rem.add_argument("--purge", action="store_true", help="Borra también configuración/datos")
    rem.add_argument("--dry-run", action="store_true")
    rem.add_argument("--yes", "-y", action="store_true")

    info = sub.add_parser("info", help="Detalle de un paquete")
    info.add_argument("target")
    return parser


def _print_packages(packages: list[Package], limit: int = 0) -> None:
    rows = packages[:limit] if limit else packages
    if not rows:
        print("No hay resultados.")
        return
    name_width = min(max(len(p.name) for p in rows), 42)
    for pkg in rows:
        name = pkg.name if len(pkg.name) <= name_width else pkg.name[: name_width - 1] + "…"
        print(
            f"{pkg.source:<8} {name:<{name_width}} {pkg.version[:18]:<18} "
            f"{human_size(pkg.size_bytes):>10}  {pkg.summary[:60]}"
        )
    print(f"\n{len(packages)} paquete(s).")


def _find(target: str) -> Package | None:
    source_id, _, package_id = target.partition(":")
    if not package_id:
        print("Formato esperado: source:id (por ejemplo apt:htop)", file=sys.stderr)
        return None
    result = scan_sync(include_orphans=False)
    for pkg in result.packages:
        if pkg.source == source_id and pkg.id == package_id:
            return pkg
    return None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "list":
        result = scan_sync(include_orphans=False)
        packages = result.packages
        if args.source:
            packages = [p for p in packages if p.source == args.source]
        if not args.all:
            packages = [p for p in packages if p.manual]
        if args.search:
            packages = [p for p in packages if p.matches(args.search)]
        if args.json:
            import json

            print(json.dumps([p.to_dict() for p in packages], ensure_ascii=False, indent=2))
        else:
            _print_packages(packages, args.limit)
            for source_id, message in result.errors:
                print(f"aviso: {SOURCE_MAP[source_id].label}: {message}", file=sys.stderr)
        return 0

    if args.command == "export":
        result = scan_sync()
        text = inventory.render_markdown(result, include_dependencies=args.all) if args.format == "md" else inventory.render_json(result)
        if args.out in (None, "-"):
            print(text, end="")
        else:
            path = Path(args.out).expanduser()
            path.write_text(text, encoding="utf-8")
            print(f"Inventario escrito en {path} ({len(text)} bytes)")
        return 0

    if args.command == "history":
        entries = load_history(limit=args.limit)
        if not entries:
            print("No hay historial de APT legible.")
            return 0
        for entry in entries:
            date = entry.date.strftime("%Y-%m-%d %H:%M") if entry.date else "????-??-?? ??:??"
            command = entry.command or "(sin orden registrada)"
            print(f"{date}  {entry.action_label:<14} {entry.summary}")
            print(f"{'':16}{command}")
        return 0

    if args.command == "orphans":
        result = scan_sync(include_orphans=True)
        if not result.orphans:
            print("Nada que limpiar.")
            return 0
        for orphan in result.orphans:
            print(f"{SOURCE_MAP[orphan.source].label:<12} {orphan.title}")
            print(f"{'':12} {orphan.subtitle}")
            print(f"{'':12} {human_size(orphan.size_bytes)}  ->  {display_command(orphan.argv, orphan.needs_root)}")
        return 0

    if args.command == "info":
        pkg = _find(args.target)
        if not pkg:
            print("No encontrado.", file=sys.stderr)
            return 1
        backend = get_backend(pkg.source)
        print(f"Nombre:    {pkg.name}")
        print(f"Origen:    {pkg.source_info.label}")
        print(f"Versión:   {pkg.version or '—'}")
        print(f"Tamaño:    {human_size(pkg.size_bytes)}")
        print(f"Tipo:      {pkg.kind_label}")
        print(f"Manual:    {'sí' if pkg.manual else 'no (dependencia)'}")
        print(f"Detalle:   {pkg.detail or '—'}")
        if pkg.path:
            print(f"Ruta:      {pkg.path}")
        if backend:
            argv = backend.removal_argv(pkg, purge=False)
            if argv:
                print(f"Comando:   {display_command(argv, backend.needs_root(pkg))}")
        return 0

    if args.command == "remove":
        pkg = _find(args.target)
        if not pkg:
            print("No encontrado.", file=sys.stderr)
            return 1
        backend = get_backend(pkg.source)
        if backend is None:
            print("Origen desconocido.", file=sys.stderr)
            return 1
        if pkg.protected:
            print("Ese paquete es un componente del sistema y Purgatio no lo tocará.", file=sys.stderr)
            return 2
        argv = backend.removal_argv(pkg, purge=args.purge)
        if not argv:
            print("Este paquete no se puede desinstalar automáticamente.", file=sys.stderr)
            return 2
        needs_root = backend.needs_root(pkg)
        print(f"Comando: {display_command(argv, needs_root)}")
        if args.dry_run:
            print("(simulación: no se ha ejecutado nada)")
            return 0
        if not args.yes:
            answer = input("¿Desinstalar? [s/N] ").strip().casefold()
            if answer not in ("s", "si", "sí", "y", "yes"):
                print("Cancelado.")
                return 1
        code = run_streaming(with_root(argv) if needs_root else argv, print)
        if code == 0:
            print("Hecho.")
        else:
            print(f"El comando terminó con código {code}.", file=sys.stderr)
        return code

    return 1
