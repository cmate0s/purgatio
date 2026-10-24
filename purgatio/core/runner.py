"""Ejecución de comandos, con y sin privilegios, en streaming."""

from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable, Iterable
from pathlib import Path


class PrivilegeError(RuntimeError):
    """Hace falta root y no hay forma de pedirlo (falta pkexec)."""


def _user_path_dirs() -> list[str]:
    """Directorios de herramientas de usuario que una sesión gráfica no hereda.

    Un lanzador del menú no lee ``~/.bashrc``, así que pipx, cargo, nvm, etc.
    no estarían en el PATH y se darían por «no instalados».
    """
    home = Path.home()
    candidates = [
        home / ".local" / "bin",
        home / ".cargo" / "bin",
        home / "go" / "bin",
        home / ".volta" / "bin",
        home / ".local" / "share" / "pnpm",
        Path("/snap/bin"),
        Path("/home/linuxbrew/.linuxbrew/bin"),
        home / ".linuxbrew" / "bin",
        # conda no suele estar en el PATH: solo su carpeta «condabin», que no añade python ni pip
        *(home / name / "condabin" for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge", "micromamba")),
    ]
    nvm = sorted(glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "bin")))
    candidates.extend(Path(p) for p in nvm[-1:])
    return [str(p) for p in candidates if p.is_dir()]


def extend_path() -> None:
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [d for d in _user_path_dirs() if d not in current]
    if extra:
        os.environ["PATH"] = os.pathsep.join([*current, *extra]) if current != [""] else os.pathsep.join(extra)


extend_path()


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
        raise PrivilegeError("Hace falta pkexec (polkit) para pedir permisos de administrador.")
    return [PKEXEC, "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive", *argv]


def display_command(argv: list[str], needs_root: bool) -> str:
    """Representación legible del comando, para mostrarla en la interfaz."""
    try:
        parts = with_root(argv) if needs_root else argv
    except PrivilegeError:
        parts = ["(requiere root; falta pkexec)", *argv]
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
    ``cancel`` y ``timeout`` terminan el grupo de procesos entero, no solo el
    primero. Los comandos con pkexec corren como root y no se pueden señalizar
    desde aquí: para ellos ``cancel`` y ``timeout`` se ignoran (matar apt a mitad
    de una transacción de dpkg es peor que esperar).
    """
    env = os.environ.copy()
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    if env_extra:
        env.update(env_extra)
    privileged = bool(PKEXEC) and argv[:1] == [PKEXEC]
    if privileged:
        cancel, timeout = None, None
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
            start_new_session=True,
        )
    except FileNotFoundError:
        on_line(f"No se encontró el ejecutable: {argv[0]}")
        return 127

    stop = threading.Event()
    reason: list[str] = []

    def _terminate() -> None:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                proc.terminate()

    def _watch() -> None:
        waited = 0.0
        while not stop.wait(0.2):
            waited += 0.2
            if cancel is not None and cancel.is_set():
                reason.append("Cancelado por el usuario.")
                _terminate()
                return
            if timeout and waited >= timeout:
                reason.append(f"Tiempo agotado tras {timeout} s.")
                _terminate()
                return

    watcher = None
    if cancel is not None or timeout:
        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        proc.wait()
    finally:
        stop.set()
    for message in reason:
        on_line(message)
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
