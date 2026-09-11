import os
import time
import threading
import urllib.request
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, Gio, GLib, Pango, Gdk

from .state import (
    KIWIX_CATEGORIES,
    KIWIX_LANGUAGES,
    fetch_kiwix_catalog,
    format_byte_size,
    get_library_folder,
    set_library_folder,
    describe_download_error,
    resolve_display_path,
    get_cached_icon_bytes,
    store_cached_icon_bytes,
)

# In-process cache so icons already fetched this session are applied
# instantly, without even touching the on-disk cache.
_ICON_MEMORY_CACHE = {}

class KiwixLibraryDialog(Adw.Dialog):
    def __init__(self):
        super().__init__()
        self.set_content_width(680)
        self.set_content_height(600)
        self.set_title("Kiwix Library")

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(
            Adw.WindowTitle(title="Kiwix Library", subtitle="browse.library.kiwix.org")
        )
        toolbar_view.add_top_bar(header_bar)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        controls.set_margin_top(12)
        controls.set_margin_bottom(12)
        controls.set_margin_start(12)
        controls.set_margin_end(12)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Search ZIM files… (e.g. Wikipedia, TED)")
        self.search_entry.connect("activate", self._on_search_activate)
        search_row.append(self.search_entry)

        search_button = Gtk.Button(label="Search")
        search_button.add_css_class("suggested-action")
        search_button.connect("clicked", self._on_search_activate)
        search_row.append(search_button)

        controls.append(search_row)
        filters_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filters_row.set_homogeneous(True)

        self.language_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new([label for _code, label in KIWIX_LANGUAGES])
        )
        self.language_dropdown.set_tooltip_text("Language")
        self.language_dropdown.set_hexpand(True)
        filters_row.append(self.language_dropdown)

        self.category_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new([label for _code, label in KIWIX_CATEGORIES])
        )
        self.category_dropdown.set_tooltip_text("Category")
        self.category_dropdown.set_hexpand(True)
        filters_row.append(self.category_dropdown)

        controls.append(filters_row)

        root_box.append(controls)
        root_box.append(Gtk.Separator())

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        root_box.append(self.stack)

        self.prompt_status = Adw.StatusPage(
            title="Browse the Kiwix Library",
            description="Search for a topic, or just hit Search to see what's available.",
            icon_name="network-server-symbolic",
        )
        self.stack.add_named(self.prompt_status, "prompt")

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_vexpand(True)

        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.start()
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Searching the Kiwix library…"))
        self.stack.add_named(loading_box, "loading")

        self.error_status = Adw.StatusPage(
            title="Couldn't Reach the Library",
            description="Check your internet connection and try again.",
            icon_name="network-offline-symbolic",
        )
        self.stack.add_named(self.error_status, "error")

        self.empty_status = Adw.StatusPage(
            title="No Results",
            description="Try a different search term or filter.",
            icon_name="edit-find-symbolic",
        )
        self.stack.add_named(self.empty_status, "empty")

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_vexpand(True)

        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_valign(Gtk.Align.START)
        self.flow_box.set_max_children_per_line(4)
        self.flow_box.set_min_children_per_line(2)
        self.flow_box.set_row_spacing(10)
        self.flow_box.set_column_spacing(10)
        self.flow_box.set_homogeneous(True)
        self.flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow_box.set_margin_top(12)
        self.flow_box.set_margin_bottom(12)
        self.flow_box.set_margin_start(12)
        self.flow_box.set_margin_end(12)

        results_scroll.set_child(self.flow_box)
        self.stack.add_named(results_scroll, "results")

        self.stack.set_visible_child_name("prompt")
        toolbar_view.set_content(root_box)
        self.set_child(toolbar_view)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _selected_code(self, dropdown, options):
        index = dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(options):
            return ""
        return options[index][0]

    def _on_search_activate(self, *_args):
        query_text = self.search_entry.get_text().strip()
        language_code = self._selected_code(self.language_dropdown, KIWIX_LANGUAGES)
        category_code = self._selected_code(self.category_dropdown, KIWIX_CATEGORIES)

        self.stack.set_visible_child_name("loading")

        def worker():
            try:
                entries = fetch_kiwix_catalog(
                    query_text=query_text,
                    language=language_code,
                    category=category_code,
                )
            except Exception as exc:
                GLib.idle_add(self._on_search_error, str(exc))
                return
            GLib.idle_add(self._on_search_results, entries)

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_error(self, message):
        self.error_status.set_description(message)
        self.stack.set_visible_child_name("error")

    def _on_search_results(self, entries):
        child = self.flow_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.flow_box.remove(child)
            child = next_child

        if not entries:
            self.stack.set_visible_child_name("empty")
            return

        for entry in entries:
            self.flow_box.append(self._build_result_card(entry))
        self.stack.set_visible_child_name("results")

    def _show_error_popup(self, title, message):
        status = Adw.StatusPage(
            title=title,
            description=message,
            icon_name="dialog-error-symbolic",
        )
        status.set_vexpand(True)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)

        ok_button = Gtk.Button(label="OK")
        ok_button.add_css_class("suggested-action")
        header.pack_end(ok_button)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(status)

        error_dialog = Adw.Dialog()
        error_dialog.set_content_width(420)
        error_dialog.set_content_height(280)
        error_dialog.set_child(toolbar_view)

        ok_button.connect("clicked", lambda b: error_dialog.close())
        error_dialog.present(self)

    def _build_result_card(self, entry):

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.set_size_request(140, 150)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.set_margin_start(4)
        card.set_margin_end(4)

        if entry.get("summary"):
            card.set_tooltip_text(entry["summary"])

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_vexpand(True)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(10)
        inner.set_margin_end(10)
        card.append(inner)

        icon_image = Gtk.Image.new_from_icon_name("network-server-symbolic")
        icon_image.set_pixel_size(40)
        icon_image.set_halign(Gtk.Align.CENTER)
        inner.append(icon_image)

        title_label = Gtk.Label(label=entry["title"], wrap=True, justify=Gtk.Justification.CENTER)
        title_label.set_halign(Gtk.Align.CENTER)
        title_label.set_lines(2)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.add_css_class("heading")
        inner.append(title_label)

        meta_bits = [bit for bit in (entry.get("category"), entry.get("language")) if bit]
        if meta_bits:
            meta_label = Gtk.Label(label=" • ".join(meta_bits), wrap=True, justify=Gtk.Justification.CENTER)
            meta_label.set_halign(Gtk.Align.CENTER)
            meta_label.add_css_class("dim-label")
            meta_label.add_css_class("caption")
            inner.append(meta_label)

        size_label = Gtk.Label(label=format_byte_size(entry.get("size_bytes")))
        size_label.set_halign(Gtk.Align.CENTER)
        size_label.add_css_class("dim-label")
        size_label.add_css_class("caption")
        inner.append(size_label)

        download_url = entry.get("download_url")
        if download_url:
            filename = download_url.split("/")[-1]

            progress_bar = Gtk.ProgressBar()
            progress_bar.set_hexpand(True)
            progress_bar.set_show_text(False)
            progress_bar.set_visible(False)
            inner.append(progress_bar)

            download_btn = Gtk.Button(icon_name="folder-download-symbolic")
            download_btn.add_css_class("flat")
            download_btn.add_css_class("circular")
            download_btn.set_halign(Gtk.Align.CENTER)
            download_btn.set_tooltip_text("Download ZIM file…")

            def start_download(url, target_path):
                download_btn.set_sensitive(False)
                download_btn.set_tooltip_text("Connecting…")
                progress_bar.set_visible(True)
                progress_bar.set_fraction(0.0)
                progress_bar.set_text("Connecting…")

                pulse_state = {"source_id": GLib.timeout_add(100, lambda: progress_bar.pulse())}

                def stop_connecting_pulse():
                    if pulse_state["source_id"] is not None:
                        GLib.source_remove(pulse_state["source_id"])
                        pulse_state["source_id"] = None
                    return False

                def update_progress(downloaded, total):
                    stop_connecting_pulse()
                    if total > 0:
                        fraction = min(downloaded / total, 1.0)
                        progress_bar.set_fraction(fraction)
                        progress_bar.set_text(f"{int(fraction * 100)}%")
                    else:
                        progress_bar.pulse()
                    return False

                def download_finished(success, message=""):
                    stop_connecting_pulse()
                    if success:
                        progress_bar.set_fraction(1.0)
                        progress_bar.set_text("Downloaded")
                        download_btn.set_icon_name("checkbox-checked-symbolic")
                        download_btn.set_sensitive(False)
                        download_btn.set_tooltip_text(f"Saved to {resolve_display_path(target_path)}")
                    else:
                        progress_bar.set_text("Failed — click to retry")
                        download_btn.set_sensitive(True)
                        download_btn.set_tooltip_text(f"Download failed: {message}")
                        self._show_error_popup(
                            "Download Failed",
                            f"Couldn't download \"{entry.get('title', 'this file')}\".\n\n{message}",
                        )
                    return False

                def download_worker():
                    tmp_path = target_path.with_name(target_path.name + ".part")
                    try:
                        req = urllib.request.Request(
                            url, headers={"User-Agent": "WebArchivesGtk/1.0"}
                        )
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            GLib.idle_add(stop_connecting_pulse)
                            content_len = resp.headers.get("Content-Length")
                            server_size = int(content_len) if content_len else None
                            total_size = server_size or entry.get("size_bytes") or 0

                            downloaded = 0
                            block_size = 262144
                            last_ui_update = 0.0

                            with open(tmp_path, "wb") as f:
                                while True:
                                    buffer = resp.read(block_size)
                                    if not buffer:
                                        break
                                    downloaded += len(buffer)
                                    f.write(buffer)
                                    now = time.monotonic()
                                    if now - last_ui_update > 0.2:
                                        last_ui_update = now
                                        GLib.idle_add(update_progress, downloaded, total_size)

                        if downloaded == 0:
                            raise IOError("Downloaded file is empty.")

                        if server_size and downloaded < server_size:
                            raise IOError(
                                f"Incomplete download: got {downloaded} of {server_size} bytes"
                            )

                        os.replace(tmp_path, target_path)
                        GLib.idle_add(update_progress, downloaded, downloaded or total_size)
                        GLib.idle_add(download_finished, True)
                    except Exception as e:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        GLib.idle_add(download_finished, False, describe_download_error(e))

                threading.Thread(target=download_worker, daemon=True).start()

            def on_folder_chosen_for_download(dialog, result, url=download_url, suggested_name=filename):
                try:
                    gfile = dialog.select_folder_finish(result)
                except GLib.Error as e:
                    if not e.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                        self._show_error_popup("Couldn't Choose Folder", str(e))
                    return

                folder_path = gfile.get_path()
                if not folder_path:
                    self._show_error_popup(
                        "Couldn't Choose Folder",
                        "That location isn't a local folder Web Archives can write to.",
                    )
                    return

                set_library_folder(folder_path)
                start_download(url, Path(folder_path) / suggested_name)

            def begin_download(btn, url=download_url, suggested_name=filename):
                folder = get_library_folder()
                if folder:
                    start_download(url, Path(folder) / suggested_name)
                    return

                folder_dialog = Gtk.FileDialog()
                folder_dialog.set_title("Choose a ZIMs Folder")
                folder_dialog.select_folder(self.get_root(), None, on_folder_chosen_for_download)

            download_btn.connect("clicked", begin_download)
            inner.append(download_btn)

        icon_url = entry.get("icon_url")
        if icon_url:
            self._load_card_icon(icon_url, icon_image)
        return card

    def _load_card_icon(self, url, image_widget):
        # Fastest path: already fetched this session, apply immediately.
        cached = _ICON_MEMORY_CACHE.get(url)
        if cached is not None:
            self._apply_card_icon(image_widget, cached)
            return

        def worker():
            data = get_cached_icon_bytes(url)
            if data is None:
                try:
                    request = urllib.request.Request(
                        url, headers={"User-Agent": "WebArchivesGtk/1.0"}
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = response.read()
                except Exception:
                    return
                store_cached_icon_bytes(url, data)

            _ICON_MEMORY_CACHE[url] = data
            GLib.idle_add(self._apply_card_icon, image_widget, data)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_card_icon(self, image_widget, data):
        try:
            gicon = Gio.BytesIcon.new(GLib.Bytes.new(data))
            image_widget.set_from_gicon(gicon)
            image_widget.set_pixel_size(40)
        except Exception:
            pass
