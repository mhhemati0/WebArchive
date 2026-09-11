import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GObject

from .state import (
    BOOKMARK_ICON_OUTLINE,
    get_library_folder,
    set_library_folder,
    scan_library_folder,
    get_full_zim_details,
)
from .kiwix_lib import KiwixLibraryDialog

class HomePageView(Gtk.ScrolledWindow):
    __gsignals__ = {
        "open-zim": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "history-clicked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "bookmarks-clicked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "search-clicked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._file_rows = []
        self.loading_row = None
        self.spinner = None

        clamp = Adw.Clamp(
            maximum_size=650,
            margin_top=24,
            margin_bottom=24,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(content_box)

        self.local_group = Adw.PreferencesGroup(title="Library")

        header_buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.reload_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.reload_button.add_css_class("flat")
        self.reload_button.set_valign(Gtk.Align.CENTER)
        self.reload_button.set_tooltip_text("Refresh Library")
        self.reload_button.connect("clicked", self.on_reload_clicked)
        header_buttons_box.append(self.reload_button)

        self.folder_button = Gtk.Button(icon_name="folder-symbolic")
        self.folder_button.add_css_class("flat")
        self.folder_button.set_valign(Gtk.Align.CENTER)
        self.folder_button.set_tooltip_text("Choose ZIMs Folder…")
        self.folder_button.connect("clicked", self.on_choose_folder_clicked)
        header_buttons_box.append(self.folder_button)

        self.local_group.set_header_suffix(header_buttons_box)
        content_box.append(self.local_group)

        remote_group = Adw.PreferencesGroup(
            title="Remote Archives",
            description="Online ZIM repositories and mirrors.",
        )
        remote_row = Adw.ActionRow(
            title="Kiwix / Internet Archive Catalog",
            subtitle="Browse and download ZIM files online",
        )
        remote_row.add_prefix(Gtk.Image.new_from_icon_name("network-server-symbolic"))
        remote_row.set_activatable(True)
        remote_row.connect("activated", self._on_remote_row_activated)
        remote_group.add(remote_row)

        content_box.append(remote_group)
        self._refresh_folder_state()

    def _refresh_folder_state(self):
        folder = get_library_folder()
        if folder:
            self.folder_button.set_tooltip_text(f"Change ZIMs Folder (currently {folder})")
            self.reload_button.set_sensitive(True)
            self._load_library()
        else:
            self.folder_button.set_tooltip_text("Choose ZIMs Folder…")
            self.reload_button.set_sensitive(False)
            self._show_no_folder_prompt()

    def _show_no_folder_prompt(self):
        self._clear_file_rows()
        row = Adw.ActionRow(
            title="No ZIMs folder selected",
            subtitle="Choose a folder to keep your ZIM files in — downloads will be saved there too.",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))

        choose_btn = Gtk.Button(label="Choose Folder…")
        choose_btn.add_css_class("suggested-action")
        choose_btn.set_valign(Gtk.Align.CENTER)
        choose_btn.connect("clicked", self.on_choose_folder_clicked)
        row.add_suffix(choose_btn)

        self.local_group.add(row)
        self._file_rows.append(row)

    def on_choose_folder_clicked(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose ZIMs Folder")
        dialog.select_folder(self.get_root(), None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result):
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error as e:
            if not e.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                print(f"Couldn't choose folder: {e}")
            return

        path = gfile.get_path()
        if not path:
            return

        set_library_folder(path)
        self._refresh_folder_state()

    def _load_library(self):
        self._clear_file_rows()
        self.loading_row = Adw.ActionRow(title="Scanning folder…")
        self.spinner = Gtk.Spinner()
        self.spinner.start()
        self.loading_row.add_suffix(self.spinner)
        self.local_group.add(self.loading_row)
        self.reload_button.set_sensitive(False)

        scan_library_folder(self.on_library_loaded)

    def _clear_file_rows(self):
        for row in self._file_rows:
            self.local_group.remove(row)
        self._file_rows = []

    def on_reload_clicked(self, button):
        self._load_library()

    def on_library_loaded(self, zim_files):
        if self.loading_row is not None:
            self.local_group.remove(self.loading_row)
            self.loading_row = None
            self.spinner = None

        self.reload_button.set_sensitive(True)
        self._clear_file_rows()

        if zim_files:
            for zim in zim_files:
                row = Adw.ActionRow(title=zim["display_name"], subtitle=zim["size"])

                gicon = zim.get("gicon")
                if gicon is not None:
                    favicon_image = Gtk.Image.new_from_gicon(gicon)
                    favicon_image.set_pixel_size(32)
                    row.add_prefix(favicon_image)
                else:
                    row.add_prefix(Gtk.Image.new_from_icon_name("book-open-symbolic"))

                row.set_activatable(True)
                row.connect("activated", self._on_zim_row_activated, zim["path"])

                hist_btn = Gtk.Button(icon_name="document-open-recent-symbolic")
                hist_btn.add_css_class("flat")
                hist_btn.set_valign(Gtk.Align.CENTER)
                hist_btn.set_tooltip_text("History")
                hist_btn.connect("clicked", lambda b, p=zim["path"]: self.emit("history-clicked", p))
                row.add_suffix(hist_btn)

                bookmark_btn = Gtk.Button(icon_name=BOOKMARK_ICON_OUTLINE)
                bookmark_btn.add_css_class("flat")
                bookmark_btn.set_valign(Gtk.Align.CENTER)
                bookmark_btn.set_tooltip_text("Bookmarks")
                bookmark_btn.connect("clicked", lambda b, p=zim["path"]: self.emit("bookmarks-clicked", p))
                row.add_suffix(bookmark_btn)

                search_btn = Gtk.Button(icon_name="system-search-symbolic")
                search_btn.add_css_class("flat")
                search_btn.set_valign(Gtk.Align.CENTER)
                search_btn.set_tooltip_text("Search Articles")
                search_btn.connect("clicked", lambda b, p=zim["path"]: self.emit("search-clicked", p))
                row.add_suffix(search_btn)

                info_button = Gtk.Button(icon_name="view-more-symbolic")
                info_button.add_css_class("flat")
                info_button.set_valign(Gtk.Align.CENTER)
                info_button.set_tooltip_text("File details")
                info_button.connect("clicked", self._on_zim_info_clicked, zim)
                row.add_suffix(info_button)

                self.local_group.add(row)
                self._file_rows.append(row)
        else:
            empty_row = Adw.ActionRow(
                title="No ZIM files found",
                subtitle=f"Add .zim files to {get_library_folder()}, then hit refresh.",
            )
            empty_row.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))
            self.local_group.add(empty_row)
            self._file_rows.append(empty_row)

    def _on_zim_info_clicked(self, button, zim):
        details = get_full_zim_details(zim["path"])

        dialog = Adw.Dialog()
        dialog.set_content_width(520)
        dialog.set_content_height(720)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="Details", subtitle=details["title"])
        header_bar.set_title_widget(title_widget)
        toolbar_view.add_top_bar(header_bar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        content_grid = Gtk.Grid()
        content_grid.set_column_spacing(20)
        content_grid.set_row_spacing(12)
        content_grid.set_margin_top(20)
        content_grid.set_margin_bottom(24)
        content_grid.set_margin_start(24)
        content_grid.set_margin_end(24)
        content_grid.set_halign(Gtk.Align.CENTER)

        row_idx = 0

        def add_detail_row(label_text, widget):
            nonlocal row_idx
            lbl = Gtk.Label(label=label_text)
            lbl.set_halign(Gtk.Align.END)
            lbl.set_valign(Gtk.Align.CENTER)
            lbl.add_css_class("dim-label")
            content_grid.attach(lbl, 0, row_idx, 1, 1)

            widget.set_halign(Gtk.Align.START)
            widget.set_valign(Gtk.Align.CENTER)
            content_grid.attach(widget, 1, row_idx, 1, 1)
            row_idx += 1

        icon_img = Gtk.Image.new_from_gicon(details["gicon"]) if details["gicon"] else Gtk.Image.new_from_icon_name("book-open-symbolic")
        icon_img.set_pixel_size(48)
        add_detail_row("Favicon", icon_img)

        title_label = Gtk.Label(label=details["title"], wrap=True, max_width_chars=35)
        title_label.set_xalign(0)
        add_detail_row("Title", title_label)

        location_label = Gtk.Label(
            label=f'<a href="file://{details["location"]}">{details["location"]}</a>',
            use_markup=True,
            wrap=True,
            max_width_chars=35,
        )
        location_label.set_xalign(0)
        add_detail_row("Location", location_label)

        fields = [
            ("Date", details["date"]),
            ("Lang", details["lang"]),
            ("Size", details["size"]),
            ("Name", details["name"]),
            ("Id", details["id"]),
            ("Description", details["description"]),
            ("Article count", details["article_count"]),
            ("Media count", details["media_count"]),
            ("Creator", details["creator"]),
            ("Publisher", details["publisher"]),
            ("Tags", details["tags"]),
        ]

        for caption, val in fields:
            val_label = Gtk.Label(label=val, wrap=True, selectable=True, max_width_chars=35)
            val_label.set_xalign(0)
            add_detail_row(caption, val_label)

        scroll.set_child(content_grid)
        toolbar_view.set_content(scroll)
        dialog.set_child(toolbar_view)
        dialog.present(self.get_root())

    def _on_zim_row_activated(self, row, path):
        self.emit("open-zim", path, "")

    def _on_remote_row_activated(self, row):
        dialog = KiwixLibraryDialog()
        dialog.connect("closed", lambda d: self._refresh_folder_state())
        dialog.present(self.get_root())
