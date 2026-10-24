"""Diálogos: progreso con streaming, detalles del paquete."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..core.models import Package, human_size  # noqa: E402


class ProgressDialog(Adw.Dialog):
    """Ventana modal que muestra en vivo la salida del comando."""

    def __init__(self, title: str, command: str, parent: Gtk.Widget) -> None:
        super().__init__()
        self.set_content_width(760)
        self.set_content_height(460)
        self.set_can_close(False)
        self.finished = False
        self.cancel_event = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        self.title_widget = Adw.WindowTitle(title=title, subtitle=None)
        header.set_title_widget(self.title_widget)
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(12)
        body.set_margin_bottom(12)
        body.set_margin_start(12)
        body.set_margin_end(12)

        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(16, 16)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.append(self.spinner)
        self.status = Gtk.Label(label="Ejecutando…", xalign=0.0)
        self.status.add_css_class("dim-label")
        self.status.set_ellipsize(2)
        status_box.append(self.status)
        body.append(status_box)

        self.buffer = Gtk.TextBuffer()
        self.buffer.set_text(command + "\n\n")
        self.view = Gtk.TextView(buffer=self.buffer)
        self.view.set_editable(False)
        self.view.set_monospace(True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_top_margin(8)
        self.view.set_bottom_margin(8)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.add_css_class("purgatio-log")

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.view)
        scrolled.add_css_class("card")
        body.append(scrolled)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)
        self.cancel_button = Gtk.Button(label="Cancelar")
        self.cancel_button.connect("clicked", self._on_cancel)
        footer.append(self.cancel_button)
        self.close_button = Gtk.Button(label="Cerrar")
        self.close_button.add_css_class("suggested-action")
        self.close_button.set_sensitive(False)
        self.close_button.connect("clicked", lambda _b: self.close())
        footer.append(self.close_button)
        body.append(footer)

        toolbar.set_content(body)
        self.set_child(toolbar)
        self.spinner.start()

    def append(self, line: str) -> None:
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, line + "\n")
        adj = self.view.get_vadjustment()
        if adj is not None:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    def finish(self, ok: bool, message: str | None = None) -> None:
        self.finished = True
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.status.set_label(message or ("Completado" if ok else "Terminó con errores"))
        self.cancel_button.set_visible(False)
        self.close_button.set_sensitive(True)
        self.set_can_close(True)
        if ok:
            self.close_button.add_css_class("suggested-action")

    def _on_cancel(self, _button) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
        self.status.set_label("Cancelando…")
        self.cancel_button.set_sensitive(False)


class DetailDialog(Adw.Dialog):
    """Detalle de un paquete con el comando exacto que se ejecutará."""

    def __init__(self, package: Package, command: str, on_remove) -> None:
        super().__init__()
        self.set_content_width(620)
        self.set_content_height(540)
        self.package = package

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title=package.name, subtitle=package.source_info.label))
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        group.set_title("Información")
        page.add(group)

        def add(title: str, value: str) -> None:
            if not value:
                return
            row = Adw.ActionRow()
            row.set_title(title)
            label = Gtk.Label(label=value, xalign=1.0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_selectable(True)
            row.add_suffix(label)
            group.add(row)

        add("Origen", package.source_info.label)
        add("Versión", package.version)
        add("Tamaño", human_size(package.size_bytes) if package.size_bytes else "")
        add("Tipo", package.kind_label)
        add("Instalado por", "ti (manual)" if package.manual else "dependencia automática")
        add("Detalle", package.detail)
        add("Ruta", package.path)
        add("Identificador", package.id)
        if package.summary:
            desc = Adw.PreferencesGroup()
            desc.set_title("Descripción")
            row = Adw.ActionRow()
            row.set_title(package.summary)
            row.set_subtitle(package.summary if package.summary != package.detail else "")
            desc.add(row)
            page.add(desc)

        if command:
            cmd_group = Adw.PreferencesGroup()
            cmd_group.set_title("Orden que se ejecutará")
            cmd_group.set_description("Purgatio no inventa comandos: esto es exactamente lo que se lanzará.")
            cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            cmd_box.set_margin_top(8)
            cmd_box.set_margin_bottom(8)
            cmd_box.set_margin_start(12)
            cmd_box.set_margin_end(6)
            label = Gtk.Label(label=command, xalign=0.0, selectable=True)
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.add_css_class("monospace")
            label.add_css_class("purgatio-subtitle")
            label.set_hexpand(True)
            cmd_box.append(label)
            copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
            copy.set_valign(Gtk.Align.CENTER)
            copy.add_css_class("flat")
            copy.set_tooltip_text("Copiar la orden")
            copy.connect("clicked", lambda _b: self._copy(command))
            cmd_box.append(copy)
            cmd_group.add(cmd_box)
            page.add(cmd_group)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(12)
        footer.set_margin_bottom(12)
        footer.set_margin_start(18)
        footer.set_margin_end(18)
        footer.set_halign(Gtk.Align.END)
        close = Gtk.Button(label="Cerrar")
        close.connect("clicked", lambda _b: self.close())
        footer.append(close)
        if not package.protected and command:
            remove = Gtk.Button(label="Desinstalar")
            remove.add_css_class("destructive-action")
            remove.connect("clicked", lambda _b: (self.close(), on_remove(package)))
            footer.append(remove)
        page.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(page)
        body.append(Gtk.Separator())
        body.append(footer)
        toolbar.set_content(body)
        self.set_child(toolbar)

    def _copy(self, text: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)
