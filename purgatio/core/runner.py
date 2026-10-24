"""Ejecución de comandos, con y sin privilegios, en streaming."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable


def which(name: str) -> str | None:
    return shutil.which(name)


def is_root() -> bool:
    return os.geteuid() == 0


PKEXEC = which("pkexec")


def with_root(argv: list[str]) -> list[str]:
    """Antepone pkexec (y un entorno predecible) si hace falta."""
    if is_root():
        return argv
    if not PKEXEC:
        return argv
    return [PKEXEC, "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive", *argv]


def display_command(argv: list[str], needs_root: bool) -> str:
    """Representación legible del comando, para mostrarla en la interfaz."""
    parts = with_root(argv) if needs_root else argv
    return " ".join(parts)


def run_streaming(
    argv: list[str],
    on_line: Callable[[str], None],
    *,
    timeout: int | None = 600,
    env_extra: dict[str, str] | None = None,
    cancel: threading.Event | None = None,
) -> int:
    """Ejecuta ``argv`` y entrega cada línea de salida a ``on_line``.

    Devuelve el código de salida. Si el proceso no existe devuelve 127.
    """
    env = os.environ.copy()
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        on_line(f"No se encontró el ejecutable: {argv[0]}")
        return 127

    timer = None
    if timeout:
        def _kill() -> None:
            if proc.poll() is None:
                proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.daemon = True
        timer.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                on_line("Cancelado por el usuario.")
                break
            on_line(line.rstrip("\n"))
        proc.wait()
    finally:
        if timer:
            timer.cancel()
    return proc.returncode


def run_capture(argv: Iterable[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Ejecuta y devuelve el resultado, en entorno C para un parseo estable."""
    env = os.environ.copy()
    env.update({"LANG": "C", "LC_ALL": "C"})
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
