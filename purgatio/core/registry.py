"""Registro de backends y escaneo paralelo del sistema."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .backends.apt_backend import AptBackend
from .backends.base import Backend
from .backends.brew_backend import BrewBackend
from .backends.conda_backend import CondaBackend
from .backends.flatpak_backend import FlatpakBackend
from .backends.go_backend import GoBackend
from .backends.npm_backend import CargoBackend, NpmBackend
from .backends.manual_backend import ManualBackend
from .backends.pip_backend import PipBackend
from .backends.pipx_backend import PipxBackend
from .backends.snap_backend import SnapBackend
from .models import Orphan, Package, SOURCE_ORDER

BACKENDS: tuple[Backend, ...] = (
    AptBackend(),
    SnapBackend(),
    FlatpakBackend(),
    PipxBackend(),
    PipBackend(),
    NpmBackend(),
    CargoBackend(),
    GoBackend(),
    BrewBackend(),
    CondaBackend(),
    ManualBackend(),
)


def get_backend(source_id: str) -> Backend | None:
    for backend in BACKENDS:
        if backend.source.id == source_id:
            return backend
    return None


@dataclass
class ScanResult:
    packages: list[Package] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


ProgressCallback = Callable[[str, list[Package] | None, str | None], None]


def safe_list(backend: Backend) -> tuple[list[Package], str | None]:
    try:
        if not backend.available():
            return [], "no disponible en este sistema"
        return backend.list_packages(), None
    except Exception as exc:  # noqa: BLE001 - un gestor roto no debe tumbar el escaneo
        return [], f"{exc.__class__.__name__}: {exc}"


def scan_sync(include_orphans: bool = True) -> ScanResult:
    result = ScanResult()
    for backend in BACKENDS:
        packages, error = safe_list(backend)
        result.packages.extend(packages)
        if error:
            result.errors.append((backend.source.id, error))
        result.counts[backend.source.id] = len(packages)
        if include_orphans and not error:
            try:
                result.orphans.extend(backend.cleanup_items())
            except Exception:
                pass
    _sort(result.packages)
    return result


def scan_async(
    on_source: ProgressCallback,
    on_done: Callable[[ScanResult], None],
    include_orphans: bool = True,
    max_workers: int = 6,
) -> threading.Thread:
    """Escanea en paralelo; los callbacks llegan desde hilos de trabajo."""

    def worker() -> None:
        result = ScanResult()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(safe_list, backend): backend for backend in BACKENDS}
            for future in as_completed(futures):
                backend = futures[future]
                packages, error = future.result()
                result.packages.extend(packages)
                result.counts[backend.source.id] = len(packages)
                if error:
                    result.errors.append((backend.source.id, error))
                on_source(backend.source.id, packages, error)
                if include_orphans and not error:
                    try:
                        found = backend.cleanup_items()
                    except Exception:
                        found = []
                    result.orphans.extend(found)
        _sort(result.packages)
        result.orphans.sort(key=lambda o: (SOURCE_ORDER.get(o.source, 99), -o.size_bytes))
        on_done(result)

    thread = threading.Thread(target=worker, name="purgatio-scan", daemon=True)
    thread.start()
    return thread


def _sort(packages: list[Package]) -> None:
    packages.sort(key=lambda p: (SOURCE_ORDER.get(p.source, 99), not p.manual, p.name.casefold()))
