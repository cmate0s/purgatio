"""Punto de entrada: GUI por defecto, CLI si se pide un subcomando."""

from __future__ import annotations

import sys

from .cli import COMMANDS


def main() -> int:
    argv = sys.argv[1:]
    if argv and (argv[0] in COMMANDS or argv[0] == "--cli"):
        from . import cli

        args = argv[1:] if argv[0] == "--cli" else argv
        return cli.main(args)

    from .ui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
