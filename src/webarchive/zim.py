import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, Gio, WebKit

from .state import get_zim_archive_metadata, register_zim_archive

class ZimPageView(Gtk.Overlay):
    def __init__(self, zim_path, window_ref, target_uri=""):
        super().__init__()
        self.zim_path = zim_path
        self.window_ref = window_ref

        title, icon = get_zim_archive_metadata(zim_path)
        self.title = title
        self.icon = icon

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.search_bar = Gtk.SearchBar()
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_box.set_margin_top(4)
        search_box.set_margin_bottom(4)
        search_box.set_margin_start(8)
        search_box.set_margin_end(8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Find in page…")
        search_box.append(self.search_entry)

        btn_prev = Gtk.Button(icon_name="go-up-symbolic")
        btn_prev.set_tooltip_text("Previous occurrence")
        btn_prev.connect("clicked", lambda *_: self.find_previous())
        search_box.append(btn_prev)

        btn_next = Gtk.Button(icon_name="go-down-symbolic")
        btn_next.set_tooltip_text("Next occurrence")
        btn_next.connect("clicked", lambda *_: self.find_next())
        search_box.append(btn_next)

        btn_close = Gtk.Button(icon_name="window-close-symbolic")
        btn_close.add_css_class("flat")
        btn_close.set_tooltip_text("Close search bar")
        btn_close.connect("clicked", lambda *_: self.hide_search_bar())
        search_box.append(btn_close)

        self.search_bar.set_child(search_box)
        self.search_bar.connect_entry(self.search_entry)
        main_box.append(self.search_bar)

        self.webview = WebKit.WebView()
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)

        self.find_controller = self.webview.get_find_controller()
        self.search_entry.connect("search-changed", self._on_find_text_changed)
        self.search_entry.connect("activate", lambda *_: self.find_next())

        self.archive_id = None
        self.archive = None
        self.initial_load_done = False

        self.webview.connect("context-menu", self._on_context_menu)
        self._last_hit_test_result = None
        self.webview.connect("mouse-target-changed", self._on_mouse_target_changed)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(2)
        gesture.connect("pressed", self._on_middle_click)
        self.webview.add_controller(gesture)

        try:
            archive_id, archive = register_zim_archive(zim_path)
            self.archive_id = archive_id
            self.archive = archive
            start_uri = target_uri if target_uri else f"zim://{archive_id}/"
            self.webview.load_uri(start_uri)
        except Exception as exc:
            self._show_error(str(exc))
            return

        main_box.append(self.webview)
        self.set_child(main_box)

    def show_search_bar(self):
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()

    def hide_search_bar(self):
        self.search_bar.set_search_mode(False)

    def _on_find_text_changed(self, entry):
        text = entry.get_text()
        if text:
            self.find_controller.search(
                text,
                WebKit.FindOptions.CASE_INSENSITIVE | WebKit.FindOptions.WRAP_AROUND,
                100,
            )
        else:
            self.find_controller.search_finish()

    def find_next(self):
        if self.search_entry.get_text():
            self.find_controller.search_next()

    def find_previous(self):
        if self.search_entry.get_text():
            self.find_controller.search_previous()

    def _on_context_menu(self, webview, context_menu, hit_test_result):
        if hit_test_result.context_is_link():
            uri = hit_test_result.get_link_uri()
            context_menu.remove_all()

            item_open = WebKit.ContextMenuItem.new_from_gaction(
                Gio.SimpleAction.new("open-link", None), "Open Link", None
            )
            item_open.get_gaction().connect(
                "activate",
                lambda *_: self.window_ref.on_open_zim_file(
                    None, self.zim_path, target_uri=uri, new_tab=False
                ),
            )
            context_menu.append(item_open)

            item_new_tab = WebKit.ContextMenuItem.new_from_gaction(
                Gio.SimpleAction.new("open-link-tab", None), "Open Link in New Tab", None
            )
            item_new_tab.get_gaction().connect(
                "activate",
                lambda *_: self.window_ref.on_open_zim_file(
                    None, self.zim_path, target_uri=uri, new_tab=True
                ),
            )
            context_menu.append(item_new_tab)

            item_copy = WebKit.ContextMenuItem.new_from_gaction(
                Gio.SimpleAction.new("copy-link", None), "Copy Link Location", None
            )
            item_copy.get_gaction().connect("activate", lambda *_: self.get_clipboard().set(uri))
            context_menu.append(item_copy)
            return False
        return False

    def _on_mouse_target_changed(self, webview, hit_test_result, modifiers):
        self._last_hit_test_result = hit_test_result

    def _on_middle_click(self, gesture, n_press, x, y):
        result = self._last_hit_test_result
        if result and result.context_is_link():
            uri = result.get_link_uri()
            if uri:
                self.window_ref.on_open_zim_file(
                    None, self.zim_path, target_uri=uri, new_tab=True
                )
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _show_error(self, message):
        status = Adw.StatusPage(
            title="Couldn't open archive",
            description=message,
            icon_name="dialog-error-symbolic",
            vexpand=True,
        )
        self.append(status)
