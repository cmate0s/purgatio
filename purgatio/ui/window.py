"""Ventana principal de Purgatio."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from ..core.history import HistoryEntry, load_history  # noqa: E402
from ..core.inventory import render_markdown, suggest_filename  # noqa: E402
from ..core.models import (  # noqa: E402
    SOURCES,
    Package,
    human_size,
)
from ..core.registry import ScanResult, get_backend, scan_async  # noqa: E402
from ..core.runner import display_command, run_streaming, with_root  # noqa: E402
from .dialogs import DetailDialog, ProgressDialog  # noqa: E402
from .rows import HistoryRow, OrphanRow, PackageItem, PackageRow  # noqa: E402

PURGE_LABEL = {
    "apt": "Borrar también la configuración (/etc y similares)",
    "snap": "Borrar también los datos guardados de la app",
    "flatpak": "Borrar también los datos de la app",
}

VIEW_SUBTITLES = {
    "cleanup": "Restos que ocupan espacio y que ningún gestor limpia solo",
    "history": "Qué se instaló, actualizó o eliminó, y con qué orden",
}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Purgatio")
        self.set_default_size(1080, 730)
        self.set_size_request(780, 500)

        self.orphans = []
        self.counts: dict[str, int] = {}
        self.view = "all"
        self.only_manual = True
        self.search_text = ""
        self.scanning = False
        self._generation = 0
        self._history: list[HistoryEntry] | None = None

        self._build_actions()

        # Modelo de datos del listado
        self.store = Gio.ListStore(item_type=PackageItem)
        self.filter = Gtk.CustomFilter.new(self._filter_func)
        self.filter_model = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.sorter = Gtk.CustomSorter.new(self._sort_func)
        self.sort_model = Gtk.SortListModel(model=self.filter_model, sorter=self.sorter)
        self.selection = Gtk.SingleSelection(model=self.sort_model, autoselect=False, can_unselect=True)
        self.filter_model.connect("items-changed", self._on_items_changed)

        self._build_ui()
        self._select_initial_view()
        self.start_scan()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        split = Adw.NavigationSplitView()
        split.set_min_sidebar_width(212)
        split.set_max_sidebar_width(300)
        split.set_sidebar(Adw.NavigationPage.new(self._build_sidebar(), "Purgatio"))
        split.set_content(Adw.NavigationPage.new(self._build_content(), "Inventario"))

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(split)
        self.set_content(self.toasts)

    def _build_sidebar(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Purgatio", subtitle="Software instalado"))
        toolbar.add_top_bar(header)

        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar.connect("row-selected", self._on_sidebar_selected)
        self.sidebar_rows: dict[str, tuple[Adw.ActionRow, Gtk.Label]] = {}
        self._add_sidebar_row("all", "Todas las apps", "applications-utilities-symbolic")
        for source in SOURCES:
            self._add_sidebar_row(source.id, source.label, source.icon)
        self.sidebar.append(Gtk.Separator(margin_top=6, margin_bottom=6))
        self._add_sidebar_row("cleanup", "Huérfanos y restos", "user-trash-full-symbolic")
        self._add_sidebar_row("history", "Historial", "document-open-recent-symbolic")

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.sidebar)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(scrolled)
        return toolbar

    def _add_sidebar_row(self, key: str, label: str, icon: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=label, activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        badge = Gtk.Label()
        badge.add_css_class("purgatio-badge")
        row.add_suffix(badge)
        row.key = key
        self.sidebar.append(row)
        self.sidebar_rows[key] = (row, badge)
        return row

    def _build_content(self) -> Gtk.Widget:
        self.header = Adw.HeaderBar()
        self.search = Gtk.SearchEntry(placeholder_text="Buscar apps instaladas…", width_chars=26)
        self.search.connect("search-changed", self._on_search_changed)
        self.search.set_tooltip_text("Busca por nombre, descripción o identificador (Ctrl+F)")
        self.header.set_title_widget(self.search)

        self.manual_toggle = Gtk.ToggleButton(label="Solo manuales", active=True)
        self.manual_toggle.set_tooltip_text("Oculta dependencias y librerías instaladas automáticamente")
        self.manual_toggle.connect("toggled", self._on_manual_toggled)
        self.header.pack_start(self.manual_toggle)

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.header.pack_end(self.spinner)

        menu = Gio.Menu()
        menu.append("Exportar inventario…", "win.export")
        menu.append("Recargar", "win.refresh")
        section = Gio.Menu()
        section.append("Atajos de teclado", "win.shortcuts")
        section.append("Acerca de Purgatio", "app.about")
        menu.append_section(None, section)
        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        self.menu_button.set_tooltip_text("Menú principal")
        self.header.pack_end(self.menu_button)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self.header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page_header.set_margin_top(14)
        page_header.set_margin_bottom(8)
        page_header.set_margin_start(20)
        page_header.set_margin_end(20)
        self.page_title = Gtk.Label(xalign=0.0)
        self.page_title.add_css_class("purgatio-big-title")
        self.page_subtitle = Gtk.Label(xalign=0.0)
        self.page_subtitle.add_css_class("purgatio-big-subtitle")
        self.page_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        page_header.append(self.page_title)
        page_header.append(self.page_subtitle)
        body.append(page_header)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.stack.add_named(self._build_list_page(), "list")
        self.stack.add_named(self._build_cleanup_page(), "cleanup")
        self.stack.add_named(self._build_history_page(), "history")
        body.append(self.stack)

        toolbar.set_content(body)
        return toolbar

    def _build_list_page(self) -> Gtk.Widget:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        self.list_view = Gtk.ListView(model=self.selection, factory=factory)
        self.list_view.set_single_click_activate(True)
        self.list_view.connect("activate", self._on_row_activated)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.list_view)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="Sin resultados",
            description="Prueba con otra búsqueda o desactiva «Solo manuales».",
        )
        self.empty_page.set_vexpand(True)

        self.list_stack = Gtk.Stack()
        self.list_stack.add_named(scrolled, "list")
        self.list_stack.add_named(self.empty_page, "empty")
        return self.list_stack

    def _build_cleanup_page(self) -> Gtk.Widget:
        self.cleanup_group = Adw.PreferencesGroup()
        self.cleanup_group.set_title("Restos detectados")
        self.cleanup_group.set_description(
            "Paquetes huérfanos, revisiones antiguas de Snap y runtimes de Flatpak que ya no usa nada."
        )
        page = Adw.PreferencesPage()
        page.add(self.cleanup_group)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(page)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return scrolled

    def _build_history_page(self) -> Gtk.Widget:
        self.history_group = Adw.PreferencesGroup()
        self.history_group.set_title("Actividad de APT")
        self.history_group.set_description(
            "Leído de /var/log/apt/history.log: la orden exacta que instaló o quitó cada cosa."
        )
        page = Adw.PreferencesPage()
        page.add(self.history_group)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(page)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return scrolled

    # ------------------------------------------------------------- acciones
    def _build_actions(self) -> None:
        export = Gio.SimpleAction.new("export", None)
        export.connect("activate", self._on_export)
        self.add_action(export)

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_: self.start_scan())
        self.add_action(refresh)

        search = Gio.SimpleAction.new("search", None)
        search.connect("activate", lambda *_: self.search.grab_focus())
        self.add_action(search)

        shortcuts = Gio.SimpleAction.new("shortcuts", None)
        shortcuts.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts)

    def _on_shortcuts(self, *_args) -> None:
        try:
            section = Adw.ShortcutsSection()
            for accel, title in (
                ("F5", "Recargar el inventario"),
                ("<Control>f", "Buscar"),
                ("<Control>e", "Exportar el inventario"),
                ("<Control>q", "Salir"),
            ):
                section.add(Adw.ShortcutsItem(accelerator=accel, title=title))
            dialog = Adw.ShortcutsDialog()
            dialog.add(section)
            dialog.present(self)
        except AttributeError:
            self._toast("Atajos: F5 recargar · Ctrl+F buscar · Ctrl+E exportar · Ctrl+Q salir")

    # -------------------------------------------------------------- escaneo
    def _select_initial_view(self) -> None:
        row = self.sidebar_rows.get("all", (None, None))[0]
        if row is not None:
            self.sidebar.select_row(row)

    def start_scan(self) -> None:
        self._generation += 1
        generation = self._generation
        self.scanning = True
        self.spinner.set_visible(True)
        self.spinner.start()
        self.store.remove_all()
        self.orphans = []
        self.counts = {}
        for _row, badge in self.sidebar_rows.values():
            badge.set_label("")
        self._update_page_header()

        scan_async(
            on_source=lambda source_id, packages, error: GLib.idle_add(
                self._on_source_ready, generation, source_id, packages, error
            ),
            on_done=lambda result: GLib.idle_add(self._on_scan_done, generation, result),
        )

    def _on_source_ready(self, generation: int, source_id: str, packages, error) -> bool:
        if generation != self._generation:
            return False
        if packages:
            self.store.splice(self.store.get_n_items(), 0, [PackageItem(p) for p in packages])
            manual = sum(1 for p in packages if p.manual)
            self.counts[source_id] = manual
            entry = self.sidebar_rows.get(source_id)
            if entry:
                entry[1].set_label(str(manual))
        elif source_id in self.sidebar_rows and error and "no disponible" in error:
            self.sidebar_rows[source_id][0].set_visible(False)
        return False

    def _on_scan_done(self, generation: int, result: ScanResult) -> bool:
        if generation != self._generation:
            return False
        self.scanning = False
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.orphans = result.orphans
        self._history = None
        self._refresh_cleanup()
        self._refresh_sidebar_badges(result)
        self._update_page_header()

        failed = [(sid, msg) for sid, msg in result.errors if "no disponible" not in msg]
        if failed:
            labels = ", ".join(sid for sid, _ in failed)
            self._toast(f"No se pudo leer: {labels}. Abre el historial de la terminal para ver el detalle.")
        return False

    def _refresh_sidebar_badges(self, result: ScanResult) -> None:
        all_entry = self.sidebar_rows.get("all")
        if all_entry:
            all_entry[1].set_label(str(sum(1 for p in result.packages if p.manual)))
        for source in SOURCES:
            entry = self.sidebar_rows.get(source.id)
            if not entry:
                continue
            count = sum(1 for p in result.packages if p.source == source.id and p.manual)
            entry[1].set_label(str(count) if count else "")
            entry[0].set_visible(count > 0 or any(s == source.id and "no disponible" not in m for s, m in result.errors))
        cleanup_badge = self.sidebar_rows.get("cleanup")
        if cleanup_badge:
            total = len(result.orphans)
            cleanup_badge[1].set_label(str(total) if total else "")
        history_badge = self.sidebar_rows.get("history")
        if history_badge:
            history_badge[1].set_label("")

    def _on_items_changed(self, *_args) -> None:
        has_items = self.filter_model.get_n_items() > 0
        self.list_stack.set_visible_child_name("list" if has_items else "empty")
        self._update_page_header()

    # ------------------------------------------------------------- filtrado
    def _filter_func(self, item, _data=None) -> bool:
        package: Package = item.package
        if self.view in ("cleanup", "history"):
            return False
        if self.view != "all" and package.source != self.view:
            return False
        if self.only_manual and not package.manual:
            return False
        if self.search_text and not package.matches(self.search_text):
            return False
        return True

    def _sort_func(self, first, second, _data=None) -> int:
        from ..core.models import SOURCE_ORDER

        a, b = first.package, second.package
        ka = (SOURCE_ORDER.get(a.source, 99), not a.manual, a.name.casefold())
        kb = (SOURCE_ORDER.get(b.source, 99), not b.manual, b.name.casefold())
        if ka < kb:
            return -1
        if ka > kb:
            return 1
        return 0

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.search_text = entry.get_text()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_manual_toggled(self, button: Gtk.ToggleButton) -> None:
        self.only_manual = button.get_active()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_sidebar_selected(self, _listbox, row) -> None:
        if row is None:
            return
        self.show_view(getattr(row, "key", "all"))

    def show_view(self, key: str) -> None:
        self.view = key
        self.manual_toggle.set_visible(key not in ("cleanup", "history"))
        self.search.set_sensitive(key not in ("cleanup", "history"))
        if key == "cleanup":
            self.stack.set_visible_child_name("cleanup")
            self._refresh_cleanup()
        elif key == "history":
            self.stack.set_visible_child_name("history")
            self._refresh_history()
        else:
            self.stack.set_visible_child_name("list")
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self.list_stack.set_visible_child_name(
                "list" if self.filter_model.get_n_items() else "empty"
            )
        self._update_page_header()

    def _update_page_header(self) -> None:
        if self.view == "cleanup":
            total = sum(o.size_bytes for o in self.orphans)
            self.page_title.set_label("Huérfanos y restos")
            subtitle = f"{len(self.orphans)} elemento(s)"
            if total:
                subtitle += f" · {human_size(total)} recuperables"
            self.page_subtitle.set_label(subtitle)
            return
        if self.view == "history":
            self.page_title.set_label("Historial de instalaciones")
            self.page_subtitle.set_label(VIEW_SUBTITLES["history"])
            return

        if self.view == "all":
            self.page_title.set_label("Todo el software instalado")
        else:
            source = next((s for s in SOURCES if s.id == self.view), None)
            self.page_title.set_label(source.label if source else "Software")

        count = self.filter_model.get_n_items()
        size = 0
        for index in range(count):
            item = self.filter_model.get_item(index)
            if item is not None:
                size += item.package.size_bytes
        bits = [f"{count} app{'s' if count != 1 else ''}"]
        if size:
            bits.append(human_size(size))
        if self.only_manual:
            bits.append("sin dependencias")
        if self.scanning:
            bits.append("analizando…")
        self.page_subtitle.set_label(" · ".join(bits))

    # ---------------------------------------------------------------- filas
    def _setup_row(self, _factory, list_item: Gtk.ListItem) -> None:
        list_item.set_child(PackageRow(self.confirm_remove, self.open_details))

    def _bind_row(self, _factory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        row = list_item.get_child()
        if item is not None and row is not None:
            row.bind(item.package)

    def _on_row_activated(self, view: Gtk.ListView, position: int) -> None:
        model = view.get_model()
        item = model.get_item(position) if model is not None else None
        if item is not None:
            self.open_details(item.package)

    # -------------------------------------------------------------- detalles
    def open_details(self, package: Package) -> None:
        backend = get_backend(package.source)
        command = ""
        if backend is not None:
            argv = backend.removal_argv(package, purge=False)
            if argv:
                command = display_command(argv, backend.needs_root(package))
        DetailDialog(package, command, self.confirm_remove).present(self)

    # --------------------------------------------------------- desinstalar
    def confirm_remove(self, package: Package) -> None:
        backend = get_backend(package.source)
        if backend is None or package.protected:
            return
        argv = backend.removal_argv(package, purge=False)
        if not argv:
            self._toast(f"«{package.name}» no se puede desinstalar desde Purgatio.")
            return
        needs_root = backend.needs_root(package)
        body = f"{package.source_info.label} · {human_size(package.size_bytes)}\n\n{display_command(argv, needs_root)}"
        dialog = Adw.AlertDialog(heading=f"¿Desinstalar «{package.name}»?", body=body)
        dialog.set_body_use_markup(False)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("remove", "Desinstalar")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        purge_check = None
        if backend.supports_purge(package):
            purge_check = Gtk.CheckButton(label=PURGE_LABEL.get(package.source, "Borrar también sus datos"))
            dialog.set_extra_child(purge_check)

        def on_response(_dialog, response: str) -> None:
            if response != "remove":
                return
            purge = bool(purge_check and purge_check.get_active())
            final_argv = backend.removal_argv(package, purge=purge)
            if not final_argv:
                return
            title = f"Desinstalando {package.name}"
            self._run_command(final_argv, needs_root, title, package=package)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _run_command(
        self,
        argv: list[str],
        needs_root: bool,
        title: str,
        package: Package | None = None,
        orphan=None,
    ) -> None:
        cancel = threading.Event()
        progress = ProgressDialog(title, display_command(argv, needs_root), self)
        progress.cancel_event = cancel

        def worker() -> None:
            code = run_streaming(
                with_root(argv) if needs_root else argv,
                lambda line: GLib.idle_add(progress.append, line),
                cancel=cancel,
            )
            GLib.idle_add(self._after_command, progress, code, package, orphan)

        threading.Thread(target=worker, name="purgatio-remove", daemon=True).start()
        progress.present(self)

    def _after_command(self, progress: ProgressDialog, code: int, package, orphan) -> bool:
        ok = code == 0
        progress.finish(ok, "Desinstalado" if ok and package else ("Limpieza completada" if ok else None))
        if ok:
            if package is not None:
                self._drop_from_store(package)
                self._toast(f"«{package.name}» desinstalado")
            elif orphan is not None:
                self._toast("Limpieza completada")
            GLib.timeout_add(600, self._rescan_after_change)
        else:
            self._toast("La operación no terminó bien: revisa el registro")
        return False

    def _rescan_after_change(self) -> bool:
        self.start_scan()
        return False

    def _drop_from_store(self, package: Package) -> None:
        for index in range(self.store.get_n_items()):
            item = self.store.get_item(index)
            if item is not None and item.package.key == package.key:
                self.store.remove(index)
                break

    # ------------------------------------------------------------- limpieza
    def _replace_rows(self, group: Adw.PreferencesGroup, attr: str, rows: list[Gtk.Widget]) -> None:
        """Sustituye las filas de un grupo (Adw no expone sus hijos internos)."""
        for row in getattr(self, attr, []):
            group.remove(row)
        setattr(self, attr, rows)
        for row in rows:
            group.add(row)

    def _refresh_cleanup(self) -> None:
        if not self.orphans:
            row = Adw.ActionRow(title="Nada que limpiar", subtitle="No hay restos detectados.")
            row.set_icon_name("emblem-ok-symbolic")
            rows: list[Gtk.Widget] = [row]
        else:
            rows = [OrphanRow(orphan, self._confirm_orphan) for orphan in self.orphans]
        self._replace_rows(self.cleanup_group, "_cleanup_rows", rows)
        self._update_page_header()

    def _confirm_orphan(self, orphan) -> None:
        dialog = Adw.AlertDialog(
            heading=f"¿Limpiar «{orphan.title}»?",
            body=f"{orphan.subtitle}\n\n{display_command(orphan.argv, orphan.needs_root)}",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("clean", "Limpiar")
        dialog.set_response_appearance("clean", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "clean":
                self._run_command(orphan.argv, orphan.needs_root, f"Limpiando {orphan.title}", orphan=orphan)

        dialog.connect("response", on_response)
        dialog.present(self)

    # -------------------------------------------------------------- historial
    def _refresh_history(self) -> None:
        if self._history is None:
            self._history = load_history(limit=150)
        if not self._history:
            rows: list[Gtk.Widget] = [
                Adw.ActionRow(title="Sin historial", subtitle="No se encontró /var/log/apt/history.log.")
            ]
        else:
            rows = [HistoryRow(entry) for entry in self._history]
        self._replace_rows(self.history_group, "_history_rows", rows)

    # -------------------------------------------------------------- exportar
    def _on_export(self, *_args) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Guardar inventario")
        dialog.set_initial_name(suggest_filename("md"))
        markdown = Gtk.FileFilter()
        markdown.set_name("Markdown")
        markdown.add_pattern("*.md")
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(markdown)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(markdown)
        dialog.save(self, None, self._on_export_done)

    def _on_export_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if not path:
            self._toast("No se pudo escribir en esa ubicación.")
            return
        result = ScanResult(packages=list(self._packages_snapshot()), orphans=list(self.orphans))
        if path.endswith(".json"):
            from ..core.inventory import render_json

            text = render_json(result)
        else:
            text = render_markdown(result, include_dependencies=not self.only_manual)
        try:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            self._toast(f"No se pudo guardar: {exc.strerror}")
            return
        self._toast(f"Inventario guardado en {path}")

    def _packages_snapshot(self):
        for index in range(self.store.get_n_items()):
            item = self.store.get_item(index)
            if item is not None:
                yield item.package

    # ----------------------------------------------------------------- utils
    def _toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(4)
        self.toasts.add_toast(toast)
