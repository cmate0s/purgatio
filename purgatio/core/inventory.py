"""Exportación del inventario a Markdown/JSON, para consultarlo offline."""

from __future__ import annotations

import json
from datetime import datetime

from .models import SOURCES, SOURCE_MAP, Package, human_size
from .registry import ScanResult


def _line_md(pkg: Package) -> str:
    bits = [f"**{pkg.name}**"]
    if pkg.version:
        bits.append(f"`{pkg.version}`")
    meta = [human_size(pkg.size_bytes)] if pkg.size_bytes else []
    if pkg.detail:
        meta.append(pkg.detail)
    bits.append("— " + " · ".join(meta) if meta else "")
    if pkg.summary:
        bits.append(f"\n  {pkg.summary}")
    return "- " + " ".join(b for b in bits if b).rstrip()


def render_markdown(result: ScanResult, include_dependencies: bool = False) -> str:
    now = datetime.now().strftime("%d/%m/%Y a las %H:%M")
    lines: list[str] = [
        "# Inventario de Purgatio",
        "",
        f"Generado el {now} en este equipo.",
        "",
        "## Resumen",
        "",
        "| Origen | Apps | Tamaño |",
        "|---|---:|---:|",
    ]
    total = 0
    for source in SOURCES:
        items = [p for p in result.packages if p.source == source.id and (include_dependencies or p.manual)]
        if not items:
            continue
        size = sum(p.size_bytes for p in items)
        total += size
        lines.append(f"| {source.label} | {len(items)} | {human_size(size)} |")
    lines.append(f"| **Total** | | **{human_size(total)}** |")
    lines.append("")

    for source in SOURCES:
        items = [p for p in result.packages if p.source == source.id and (include_dependencies or p.manual)]
        if not items:
            continue
        lines.append(f"## {source.label} ({len(items)})")
        lines.append("")
        hidden = len([p for p in result.packages if p.source == source.id]) - len(items)
        for pkg in sorted(items, key=lambda p: p.name.casefold()):
            lines.append(_line_md(pkg))
        if hidden:
            lines.append("")
            lines.append(f"*{hidden} dependencias y componentes del sistema no listados.*")
        lines.append("")

    if result.orphans:
        lines.append("## Posibles restos a limpiar")
        lines.append("")
        for orphan in result.orphans:
            size = f" · {human_size(orphan.size_bytes)}" if orphan.size_bytes else ""
            lines.append(f"- **{orphan.title}**{size} — {orphan.subtitle}")
        lines.append("")

    if result.errors:
        lines.append("## Avisos")
        lines.append("")
        for source_id, message in result.errors:
            label = SOURCE_MAP.get(source_id).label if source_id in SOURCE_MAP else source_id
            lines.append(f"- {label}: {message}")
        lines.append("")

    lines.append("---")
    lines.append("Generado con Purgatio.")
    return "\n".join(lines) + "\n"


def render_json(result: ScanResult) -> str:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "packages": [p.to_dict() for p in result.packages],
        "orphans": [o.to_dict() for o in result.orphans],
        "errors": [{"source": s, "message": m} for s, m in result.errors],
        "counts": result.counts,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def suggest_filename(fmt: str = "md") -> str:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"inventario-purgatio-{stamp}.{fmt}"
