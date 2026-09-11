import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from .state import (
    load_persisted_state,
    setup_zim_uri_scheme,
    write_persisted_state,
    save_state,
)
from .window import WebArchivesWindow

class WebArchivesApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.mhhemati0.WebArchive",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = WebArchivesWindow(application=self)
        win.present()

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_persisted_state()
        setup_zim_uri_scheme()

        self.create_action("new-tab", self.on_new_tab, ["<Ctrl>t"])
        self.create_action("quit", self.on_quit, ["<Ctrl>q"])
        self.create_action("close-tab", self.on_close_tab, ["<Ctrl>w"])
        self.create_action("find-in-page", self.on_find_in_page, ["<Ctrl>f"])

    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def on_new_tab(self, action, param):
        win = self.get_active_window()
        if win:
            win.add_new_tab()

    def on_quit(self, action, param):
        self.quit()

    def do_shutdown(self):
        if save_state["scheduled"]:
            write_persisted_state()
        Adw.Application.do_shutdown(self)

    def on_close_tab(self, action, param):
        win = self.get_active_window()
        if win:
            win.close_current_tab()

    def on_find_in_page(self, action, param):
        win = self.get_active_window()
        if win:
            win.show_find_in_page()


