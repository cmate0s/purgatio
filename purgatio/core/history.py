"""Historial de lo instalado: el «¿qué instalé y cuándo?» de APT.

Se leen /var/log/apt/history.log y sus rotaciones comprimidas. Cada bloque
describe una transacción (instalar, actualizar, eliminar...) con fecha y
la orden exacta que la provocó.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("/var/log/apt")
PACKAGE_ENTRY = re.compile(r"^(?P<name>[^:,\s]+)(?::[^,\s]+)?\s*(?:\((?P<rest>[^)]*)\))?\s*,?\s*$")
ACTION_KEYS = {
    "Install": "install",
    "Upgrade": "upgrade",
    "Remove": "remove",
    "Purge": "purge",
    "Downgrade": "downgrade",
}


@dataclass
class HistoryEntry:
    date: datetime | None
    action: str
    command: str
    packages: list[str] = field(default_factory=list)
    automatic: int = 0

    @property
    def action_label(self) -> str:
        return {
            "install": "Instalación",
            "upgrade": "Actualización",
            "remove": "Desinstalación",
            "purge": "Purga",
            "downgrade": "Degradación",
        }.get(self.action, self.action.title())

    @property
    def summary(self) -> str:
        if self.action in ("install",):
            return ", ".join(self.packages[:6]) + ("…" if len(self.packages) > 6 else "")
        count = len(self.packages)
        return f"{count} paquete{'s' if count != 1 else ''}"


def _log_files() -> list[Path]:
    if not LOG_DIR.is_dir():
        return []
    files = [p for p in LOG_DIR.iterdir() if p.name.startswith("history.log")]
    return sorted(files)


def _read(path: Path) -> str:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, EOFError):
        return ""


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d  %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_packages(value: str) -> tuple[list[str], int]:
    names: list[str] = []
    automatic = 0
    for chunk in value.split("),"):
        chunk = chunk.strip().rstrip(")")
        if not chunk:
            continue
        name, _, rest = chunk.partition(" (")
        name = name.split(":")[0].strip()
        if name:
            names.append(name)
        if rest.strip().split(",")[-1].strip() == "automatic":
            automatic += 1
    return names, automatic


def parse_history(text: str) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []
    current_date: datetime | None = None
    current_command = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        if key == "Start-Date":
            current_date = _parse_date(value)
            current_command = ""
        elif key == "Commandline":
            current_command = value.strip()
        elif key in ACTION_KEYS and value.strip():
            packages, automatic = _parse_packages(value)
            entries.append(
                HistoryEntry(
                    date=current_date,
                    action=ACTION_KEYS[key],
                    command=current_command,
                    packages=packages,
                    automatic=automatic,
                )
            )
    entries.sort(key=lambda e: (e.date or datetime.min, e.action), reverse=True)
    return entries


def load_history(limit: int = 300) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []
    for path in _log_files():
        entries.extend(parse_history(_read(path)))
    entries.sort(key=lambda e: (e.date or datetime.min), reverse=True)
    return entries[:limit]
