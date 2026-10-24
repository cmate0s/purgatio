"""Aplicación GTK4 + Libadwaita."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import APP_ID, APP_NAME, __version__  # noqa: E402

CSS = """
.purgatio-title { font-weight: 600; }
.purgatio-subtitle { font-size: 0.85em; opacity: 0.68; }
.purgatio-size { font-size: 0.85em; opacity: 0.62; font-feature-settings: "tnum"; }
.purgatio-badge {
  font-size: 0.72em;
  opacity: 0.55;
  letter-spacing: 0.04em;
}
.purgatio-source-icon { opacity: 0.85; }
.purgatio-row { border-bottom: 1px solid alpha(currentColor, 0.07); }
.purgatio-log text { font-family: monospace; font-size: 0.85em; }
.purgatio-big-title { font-size: 1.45em; font-weight: 800; }
.purgatio-big-subtitle { opacity: 0.65; }
"""


class PurgatioApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_startup(self) -> None:  # noqa: N802 (API de GTK)
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.refresh", ["F5"])
        self.set_accels_for_action("win.export", ["<Control>e"])
        self.set_accels_for_action("win.search", ["<Control>f"])

    def do_activate(self) -> None:  # noqa: N802
        if self.window is None:
            from .window import MainWindow

            self.window = MainWindow(self)
        self.window.present()

    def _on_about(self, _action, _param) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="mate0s",
            version=__version__,
            comments=(
                "Inventario visual y desinstalación unificada de software en Linux.\n"
                "Reúne APT, Snap, Flatpak, pipx, npm, Cargo, AppImages y binarios sueltos "
                "en una sola ventana y te dice qué hay instalado y cómo quitarlo."
            ),
            license_type=Gtk.License.MIT_X11,
        )
        dialog.add_credit_section("Hecho con", ["GTK4", "Libadwaita", "python-apt"])
        dialog.present(self.window)


def _capture_window(window, path: str) -> None:
    """Renderiza la ventana a PNG (para documentación y pruebas visuales)."""
    width = window.get_width()
    height = window.get_height()
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    renderer = Gtk.Native.get_renderer(window)
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    print(f"Captura guardada en {path} ({width}x{height})", file=sys.stderr)


def main() -> int:
    argv = list(sys.argv)
    screenshot = None
    view = None
    for flag in ("--screenshot", "--view"):
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                value = argv[index + 1]
                if flag == "--screenshot":
                    screenshot = value
                else:
                    view = value
                del argv[index : index + 2]

    app = PurgatioApp()
    if screenshot or view:

        def _debug_actions() -> bool:
            window = app.get_active_window()
            if window is not None and view:
                window.show_view(view)
            if window is not None and screenshot:
                from gi.repository import GLib

                def _shoot() -> bool:
                    try:
                        _capture_window(window, screenshot)
                    except Exception as exc:  # noqa: BLE001
                        print(f"No se pudo capturar: {exc}", file=sys.stderr)
                    if not view:
                        app.quit()
                    return False

                GLib.timeout_add(900, _shoot)
            elif window is not None:
                app.quit()
            return False

        from gi.repository import GLib

        GLib.timeout_add(3200, _debug_actions)
    return app.run(argv)
