"""Filas reutilizables de la interfaz (ListView y ListBox)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from ..core.models import Orphan, Package, human_size  # noqa: E402


class PackageItem(GObject.Object):
    """Envoltorio GObject para poder meter Package en un Gio.ListStore."""

    __gtype_name__ = "PurgatioPackageItem"

    def __init__(self, package: Package) -> None:
        super().__init__()
        self.package = package


class PackageRow(Gtk.Box):
    """Fila de una app instalada."""

    def __init__(self, on_remove, on_open) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(14)
        self.set_margin_end(8)
        self.add_css_class("purgatio-row")
        self.package: Package | None = None
        self._on_remove = on_remove
        self._on_open = on_open

        self.icon = Gtk.Image(pixel_size=26)
        self.icon.add_css_class("purgatio-source-icon")
        self.icon.set_valign(Gtk.Align.CENTER)
        self.append(self.icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
        text_box.set_valign(Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0.0, ellipsize=2, single_line_mode=True)
        self.title.add_css_class("purgatio-title")
        self.subtitle = Gtk.Label(xalign=0.0, ellipsize=2, single_line_mode=True)
        self.subtitle.add_css_class("purgatio-subtitle")
        text_box.append(self.title)
        text_box.append(self.subtitle)
        self.append(text_box)

        self.badge = Gtk.Label()
        self.badge.add_css_class("purgatio-badge")
        self.badge.set_valign(Gtk.Align.CENTER)
        self.append(self.badge)

        self.size = Gtk.Label()
        self.size.add_css_class("purgatio-size")
        self.size.set_valign(Gtk.Align.CENTER)
        self.size.set_size_request(74, -1)
        self.size.set_xalign(1.0)
        self.append(self.size)

        self.lock = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
        self.lock.set_valign(Gtk.Align.CENTER)
        self.lock.set_tooltip_text("Componente del sistema: Purgatio no lo tocará")
        self.lock.add_css_class("purgatio-size")
        self.append(self.lock)

        self.remove_button = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.remove_button.set_valign(Gtk.Align.CENTER)
        self.remove_button.add_css_class("flat")
        self.remove_button.set_tooltip_text("Desinstalar")
        self.remove_button.connect("clicked", self._clicked_remove)
        self.append(self.remove_button)

    def bind(self, package: Package) -> None:
        self.package = package
        self.icon.set_from_icon_name(package.source_info.icon)
        self.title.set_label(package.name)
        bits = []
        if package.version:
            bits.append(package.version)
        if package.summary:
            bits.append(package.summary)
        elif package.detail:
            bits.append(package.detail)
        self.subtitle.set_label(" · ".join(bits))
        self.subtitle.set_tooltip_text("\n".join(filter(None, [package.summary, package.detail, package.path])))
        self.badge.set_label(package.source_info.short.casefold())
        self.size.set_label(human_size(package.size_bytes) if package.size_bytes else "")
        self.remove_button.set_visible(not package.protected)
        self.lock.set_visible(package.protected)

    def _clicked_remove(self, _button) -> None:
        if self.package is not None:
            self._on_remove(self.package)


class OrphanRow(Adw.ActionRow):
    def __init__(self, orphan: Orphan, on_clean) -> None:
        super().__init__()
        self.orphan = orphan
        self.set_title(orphan.title)
        self.set_subtitle(orphan.subtitle)
        self.set_icon_name(orphan.source_info.icon)
        if orphan.size_bytes:
            size = Gtk.Label(label=human_size(orphan.size_bytes))
            size.add_css_class("purgatio-size")
            self.add_suffix(size)
        button = Gtk.Button(label="Limpiar")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", lambda _b: on_clean(orphan))
        self.add_suffix(button)
        self.set_activatable(False)


class HistoryRow(Adw.ActionRow):
    def __init__(self, entry) -> None:
        super().__init__()
        icons = {
            "install": "list-add-symbolic",
            "upgrade": "software-update-available-symbolic",
            "remove": "user-trash-symbolic",
            "purge": "user-trash-full-symbolic",
            "downgrade": "go-down-symbolic",
        }
        self.set_icon_name(icons.get(entry.action, "document-open-recent-symbolic"))
        self.set_title(f"{entry.action_label}: {entry.summary}")
        date = entry.date.strftime("%d/%m/%Y · %H:%M") if entry.date else "fecha desconocida"
        command = entry.command or "sin orden registrada"
        self.set_subtitle(f"{date} — {command}")
        self.set_tooltip_text("\n".join([entry.action_label, date, command, ", ".join(entry.packages)]))
        self.set_activatable(False)
        self.add_css_class("purgatio-history-row")
