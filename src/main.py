import json
import os
import sys
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, Gio, GLib, GObject, Pango, WebKit, Gdk

icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
icon_theme.add_resource_path("/io/github/mhhemati0/WebArchive")

BOOKMARK_ICON_OUTLINE = "user-bookmarks-symbolic"
BOOKMARK_ICON_FILLED = "bookmark-filled-symbolic"

_OPEN_ARCHIVES = {}
BOOKMARKS = {}
HISTORY = {}
HISTORY_MAX_ENTRIES = 100
LIBRARY_FOLDER = None

_APP_DATA_DIR = Path(GLib.get_user_data_dir()) / "io.github.mhhemati0.WebArchive"
_APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = _APP_DATA_DIR / "library-state.json"

_save_state = {"scheduled": False}


def load_persisted_state():
    if not STATE_FILE.exists():
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        BOOKMARKS.update(payload.get("bookmarks", {}))
        for zim_path, entries in payload.get("history", {}).items():
            HISTORY[zim_path] = [(u, t) for u, t in entries]
        global LIBRARY_FOLDER
        folder = payload.get("library_folder")
        if folder and Path(folder).is_dir():
            LIBRARY_FOLDER = folder
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"Could not load saved library state: {e}")


def _write_persisted_state():
    try:
        payload = {
            "bookmarks": BOOKMARKS,
            "history": {zp: [[u, t] for u, t in entries] for zp, entries in HISTORY.items()},
            "library_folder": LIBRARY_FOLDER,
        }
        tmp_file = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_file, STATE_FILE)
    except OSError as e:
        print(f"Could not save library state: {e}")


def schedule_state_save():
    if _save_state["scheduled"]:
        return
    _save_state["scheduled"] = True

    def _do_save():
        _save_state["scheduled"] = False
        _write_persisted_state()
        return False

    GLib.timeout_add(500, _do_save)


try:
    from libzim.reader import Archive
    from libzim.search import Query, Searcher
except ImportError:
    pass


def is_bookmarked(zim_path, uri):
    return zim_path in BOOKMARKS and uri in BOOKMARKS[zim_path]


def toggle_bookmark(zim_path, uri, title):
    if zim_path not in BOOKMARKS:
        BOOKMARKS[zim_path] = {}
    if uri in BOOKMARKS[zim_path]:
        del BOOKMARKS[zim_path][uri]
        schedule_state_save()
        return False
    else:
        BOOKMARKS[zim_path][uri] = title or uri
        schedule_state_save()
        return True


def get_bookmarks(zim_path):
    return BOOKMARKS.get(zim_path, {})


def add_history_entry(zim_path, uri, title):
    if not zim_path or not uri:
        return
    entries = HISTORY.setdefault(zim_path, [])
    entries[:] = [(u, t) for (u, t) in entries if u != uri]
    entries.insert(0, (uri, title or uri))
    del entries[HISTORY_MAX_ENTRIES:]
    schedule_state_save()


def update_history_title(zim_path, uri, title):
    entries = HISTORY.get(zim_path)
    if not entries or not title:
        return
    for i, (u, _t) in enumerate(entries):
        if u == uri:
            entries[i] = (u, title)
            schedule_state_save()
            break


def remove_history_entry(zim_path, uri):
    entries = HISTORY.get(zim_path)
    if entries:
        entries[:] = [(u, t) for (u, t) in entries if u != uri]
        schedule_state_save()


def get_history(zim_path):
    return HISTORY.get(zim_path, [])


def clear_history(zim_path):
    HISTORY[zim_path] = []
    schedule_state_save()


def get_library_folder():
    return LIBRARY_FOLDER


def set_library_folder(path):
    global LIBRARY_FOLDER
    LIBRARY_FOLDER = path
    schedule_state_save()


KIWIX_LIBRARY_BASE = "https://library.kiwix.org"
KIWIX_ENTRIES_ENDPOINT = f"{KIWIX_LIBRARY_BASE}/catalog/v2/entries"

KIWIX_CATEGORIES = [
    ("", "Any Category"),
    ("wikipedia", "Wikipedia"),
    ("wiktionary", "Wiktionary"),
    ("wikibooks", "Wikibooks"),
    ("wikinews", "Wikinews"),
    ("wikiquote", "Wikiquote"),
    ("wikisource", "Wikisource"),
    ("wikiversity", "Wikiversity"),
    ("wikivoyage", "Wikivoyage"),
    ("ted", "TED Talks"),
    ("gutenberg", "Project Gutenberg"),
    ("phet", "PhET Simulations"),
    ("vikidia", "Vikidia"),
    ("ifixit", "iFixit"),
    ("stack_exchange", "Stack Exchange"),
    ("other", "Other"),
]

KIWIX_LANGUAGES = [
    ("", "Any Language"),
    ("eng", "English"),
    ("fra", "French"),
    ("spa", "Spanish"),
    ("deu", "German"),
    ("ita", "Italian"),
    ("por", "Portuguese"),
    ("rus", "Russian"),
    ("ara", "Arabic"),
    ("zho", "Chinese"),
    ("jpn", "Japanese"),
    ("kor", "Korean"),
    ("hin", "Hindi"),
    ("ben", "Bengali"),
    ("urd", "Urdu"),
    ("fas", "Persian"),
    ("tur", "Turkish"),
    ("vie", "Vietnamese"),
    ("ind", "Indonesian"),
    ("pol", "Polish"),
    ("nld", "Dutch"),
    ("ukr", "Ukrainian"),
    ("ron", "Romanian"),
    ("ell", "Greek"),
    ("heb", "Hebrew"),
    ("tha", "Thai"),
    ("swa", "Swahili"),
    ("amh", "Amharic"),
    ("hau", "Hausa"),
]


def _xml_local_tag(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def format_byte_size(num_bytes):
    if not num_bytes:
        return "Unknown size"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "Unknown size"


def fetch_kiwix_catalog(query_text="", language="", category="", count=40):
    params = {"count": str(count)}
    if query_text:
        params["q"] = query_text
    if language:
        params["lang"] = language
    if category:
        params["category"] = category

    url = KIWIX_ENTRIES_ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "WebArchivesGtk/1.0"})

    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read()

    root = ET.fromstring(data)
    entries = []

    for child in root:
        if _xml_local_tag(child.tag) != "entry":
            continue

        info = {
            "title": "Untitled",
            "summary": "",
            "language": "",
            "category": "",
            "size_bytes": None,
            "icon_url": None,
            "download_url": None,
        }

        for field in child:
            tag = _xml_local_tag(field.tag)
            if tag == "title":
                info["title"] = (field.text or "").strip() or "Untitled"
            elif tag == "summary":
                info["summary"] = (field.text or "").strip()
            elif tag == "language":
                info["language"] = (field.text or "").strip()
            elif tag == "category":
                info["category"] = (field.text or "").strip()
            elif tag == "link":
                rel = field.get("rel", "") or ""
                type_attr = field.get("type", "") or ""
                href = field.get("href", "") or ""
                length = field.get("length")

                if not href:
                    continue

                full_href = urllib.parse.urljoin(KIWIX_LIBRARY_BASE + "/", href)

                if type_attr.startswith("image/") and info["icon_url"] is None:
                    info["icon_url"] = full_href
                elif (
                    "acquisition" in rel or "zim" in type_attr
                ) and info["download_url"] is None:
                    if full_href.endswith(".meta4"):
                        full_href = full_href[: -len(".meta4")]
                    info["download_url"] = full_href
                    if length:
                        try:
                            info["size_bytes"] = int(length)
                        except ValueError:
                            pass

        entries.append(info)

    return entries


class KiwixLibraryDialog(Adw.Dialog):
    def __init__(self):
        super().__init__()
        self.set_content_width(1000)
        self.set_content_height(760)
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
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_margin_top(12)
        controls.set_margin_bottom(12)
        controls.set_margin_start(12)
        controls.set_margin_end(12)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Search ZIM files… (e.g. Wikipedia, TED)")
        self.search_entry.connect("activate", self._on_search_activate)
        controls.append(self.search_entry)

        self.language_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new([label for _code, label in KIWIX_LANGUAGES])
        )
        self.language_dropdown.set_tooltip_text("Language")
        controls.append(self.language_dropdown)

        self.category_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new([label for _code, label in KIWIX_CATEGORIES])
        )
        self.category_dropdown.set_tooltip_text("Category")
        controls.append(self.category_dropdown)

        search_button = Gtk.Button(label="Search")
        search_button.add_css_class("suggested-action")
        search_button.connect("clicked", self._on_search_activate)
        controls.append(search_button)

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
        self.flow_box.set_max_children_per_line(3)
        self.flow_box.set_min_children_per_line(1)
        self.flow_box.set_row_spacing(12)
        self.flow_box.set_column_spacing(12)
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
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")
        card.set_size_request(280, -1)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.set_margin_start(4)
        card.set_margin_end(4)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        card.append(inner)

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon_image = Gtk.Image.new_from_icon_name("network-server-symbolic")
        icon_image.set_pixel_size(40)
        header_row.append(icon_image)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        title_label = Gtk.Label(label=entry["title"], wrap=True)
        title_label.set_xalign(0)
        title_label.add_css_class("heading")
        title_box.append(title_label)

        meta_bits = [bit for bit in (entry.get("category"), entry.get("language")) if bit]
        if meta_bits:
            meta_label = Gtk.Label(label=" • ".join(meta_bits))
            meta_label.set_xalign(0)
            meta_label.add_css_class("dim-label")
            meta_label.add_css_class("caption")
            title_box.append(meta_label)

        header_row.append(title_box)
        inner.append(header_row)

        if entry.get("summary"):
            desc_label = Gtk.Label(label=entry["summary"], wrap=True)
            desc_label.set_xalign(0)
            desc_label.set_lines(3)
            desc_label.set_ellipsize(Pango.EllipsizeMode.END)
            desc_label.add_css_class("dim-label")
            inner.append(desc_label)

        footer_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        size_label = Gtk.Label(label=format_byte_size(entry.get("size_bytes")))
        size_label.set_xalign(0)
        size_label.set_hexpand(True)
        size_label.add_css_class("dim-label")
        footer_row.append(size_label)

        download_url = entry.get("download_url")
        if download_url:
            filename = download_url.split("/")[-1]

            progress_bar = Gtk.ProgressBar()
            progress_bar.set_hexpand(True)
            progress_bar.set_show_text(True)
            progress_bar.set_visible(False)
            inner.append(progress_bar)

            download_btn = Gtk.Button(icon_name="folder-download-symbolic")
            download_btn.add_css_class("flat")
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
                        download_btn.set_tooltip_text(f"Saved to {target_path}")
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
                        GLib.idle_add(download_finished, False, _describe_download_error(e))

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
            footer_row.append(download_btn)

        inner.append(footer_row)
        icon_url = entry.get("icon_url")
        if icon_url:
            self._load_card_icon(icon_url, icon_image)
        return card

    def _load_card_icon(self, url, image_widget):
        def worker():
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "WebArchivesGtk/1.0"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = response.read()
            except Exception:
                return
            GLib.idle_add(self._apply_card_icon, image_widget, data)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_card_icon(self, image_widget, data):
        try:
            gicon = Gio.BytesIcon.new(GLib.Bytes.new(data))
            image_widget.set_from_gicon(gicon)
            image_widget.set_pixel_size(40)
        except Exception:
            pass


def register_zim_archive(path):
    archive = Archive(path)
    archive_id = uuid.uuid4().hex
    _OPEN_ARCHIVES[archive_id] = archive
    return archive_id, archive


def zim_display_name(path):
    return Path(path).stem


def get_zim_archive_metadata(path):
    title = zim_display_name(path)
    gicon = None
    try:
        archive = Archive(path)
        try:
            raw_title = archive.get_metadata("Title")
            if isinstance(raw_title, bytes):
                raw_title = raw_title.decode("utf-8", errors="ignore")
            if raw_title and raw_title.strip():
                title = raw_title.strip()
        except Exception:
            try:
                if archive.main_entry and archive.main_entry.title:
                    m_title = archive.main_entry.title
                    if m_title and m_title.lower() != "mainpage":
                        title = m_title
            except Exception:
                pass

        try:
            illustration = archive.get_illustration_item(48)
            content = bytes(illustration.content)
            gicon = Gio.BytesIcon.new(GLib.Bytes.new(content))
        except Exception:
            gicon = None
    except Exception:
        pass
    return title, gicon


def get_full_zim_details(path):
    details = {
        "title": zim_display_name(path),
        "location": str(Path(path).parent),
        "path": path,
        "date": "N/A",
        "lang": "N/A",
        "size": "Unknown size",
        "name": Path(path).stem,
        "id": "N/A",
        "description": "N/A",
        "article_count": "N/A",
        "media_count": "N/A",
        "creator": "N/A",
        "publisher": "N/A",
        "tags": "N/A",
        "gicon": None,
    }
    try:
        full_path = Path(path)
        if full_path.exists():
            size_mb = full_path.stat().st_size / (1024 * 1024)
            details["size"] = (
                f"{size_mb / 1024:.1f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
            )

        archive = Archive(path)
        details["id"] = str(getattr(archive, "uuid", "N/A"))
        details["article_count"] = str(getattr(archive, "article_count", "N/A"))
        details["media_count"] = str(getattr(archive, "media_count", "N/A"))

        def read_meta(key):
            try:
                val = archive.get_metadata(key)
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="ignore")
                return val.strip() if val and val.strip() else None
            except Exception:
                return None

        for key, field_key in [
            ("Title", "title"), ("Date", "date"), ("Description", "desc"),
            ("Creator", "creator"), ("Publisher", "publisher"), ("Name", "name")
        ]:
            val = read_meta(key)
            if val:
                details[field_key if field_key != "desc" else "description"] = val

        lang = read_meta("Language") or read_meta("lang")
        if lang:
            details["lang"] = lang

        tags = read_meta("Tags") or read_meta("Keywords")
        if tags:
            details["tags"] = tags.replace(";", " • ")

        try:
            illustration = archive.get_illustration_item(48)
            content = bytes(illustration.content)
            details["gicon"] = Gio.BytesIcon.new(GLib.Bytes.new(content))
        except Exception:
            details["gicon"] = None
    except Exception:
        pass
    return details


def _make_glib_error(message):
    return GLib.Error.new_literal(GLib.quark_from_string("zim-scheme"), message, 0)


def _zim_uri_entry_path(uri):
    parsed = urllib.parse.urlparse(uri)
    return urllib.parse.unquote(parsed.path.lstrip("/"))


def handle_zim_uri_scheme(request):
    uri = request.get_uri()
    parsed = urllib.parse.urlparse(uri)
    archive_id = parsed.netloc
    entry_path = _zim_uri_entry_path(uri)

    archive = _OPEN_ARCHIVES.get(archive_id)
    if archive is None:
        request.finish_error(_make_glib_error("Archive is not open"))
        return

    try:
        entry = archive.get_entry_by_path(entry_path) if entry_path else archive.main_entry
        item = entry.get_item()
        content = bytes(item.content)
        mime_type = item.mimetype

        gbytes = GLib.Bytes.new(content)
        stream = Gio.MemoryInputStream.new_from_bytes(gbytes)
        request.finish(stream, len(content), mime_type)
    except Exception as exc:
        request.finish_error(_make_glib_error(str(exc)))


def setup_zim_uri_scheme():
    context = WebKit.WebContext.get_default()
    context.register_uri_scheme("zim", handle_zim_uri_scheme)


def _describe_download_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"Server returned an error (HTTP {exc.code} {exc.reason})."
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return "The connection timed out. Check your internet connection and try again."
        return f"Couldn't reach the server ({reason}). Check your internet connection."
    if isinstance(exc, TimeoutError):
        return "The connection timed out. Check your internet connection and try again."
    if isinstance(exc, PermissionError):
        return "Permission denied writing to the chosen location."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Not enough free disk space to finish this download."
    if isinstance(exc, OSError):
        return f"A file system error occurred: {exc}"
    return str(exc)


def _collect_zim_file_info(full_path):
    try:
        size_mb = full_path.stat().st_size / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
    except OSError:
        size_str = "Unknown size"

    title, gicon = get_zim_archive_metadata(str(full_path))
    return {
        "name": full_path.name,
        "display_name": title,
        "path": str(full_path),
        "size": size_str,
        "gicon": gicon,
    }


def scan_library_folder(callback):
    def worker():
        results = []
        folder = get_library_folder()
        if folder:
            folder_path = Path(folder)
            try:
                if folder_path.is_dir():
                    for entry in sorted(folder_path.iterdir()):
                        if entry.is_file() and entry.suffix.lower() == ".zim":
                            results.append(_collect_zim_file_info(entry))
            except OSError:
                pass
        GLib.idle_add(callback, results)

    threading.Thread(target=worker, daemon=True).start()


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


class WebArchivesWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(800, 600)
        self.set_title("Web Archives")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)

        title_widget = Adw.WindowTitle(title="Web Archives")
        header_bar.set_title_widget(title_widget)

        self.home_button = Gtk.Button(icon_name="go-home-symbolic", tooltip_text="Home")
        self.home_button.connect("clicked", self.on_home_clicked)
        header_bar.pack_start(self.home_button)

        self.back_button = Gtk.Button(icon_name="go-previous-symbolic")
        self.back_button.set_sensitive(False)
        self.back_button.connect("clicked", self.on_back_clicked)
        header_bar.pack_start(self.back_button)

        self.forward_button = Gtk.Button(icon_name="go-next-symbolic")
        self.forward_button.set_sensitive(False)
        self.forward_button.connect("clicked", self.on_forward_clicked)
        header_bar.pack_start(self.forward_button)

        new_tab_button = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="New Tab")
        new_tab_button.connect("clicked", self.on_new_tab_clicked)
        header_bar.pack_start(new_tab_button)

        self.bookmark_top_btn = Gtk.Button(
            icon_name=BOOKMARK_ICON_OUTLINE, tooltip_text="Bookmark Page"
        )
        self.bookmark_top_btn.set_visible(False)
        self.bookmark_top_btn.connect("clicked", self.on_top_bookmark_clicked)
        header_bar.pack_start(self.bookmark_top_btn)

        self.zim_popover = Gtk.Popover(autohide=True)
        self.zim_menu_button = Gtk.MenuButton(
            icon_name="view-more-symbolic",
            popover=self.zim_popover,
            tooltip_text="Page Options",
        )
        self.zim_menu_button.set_visible(False)
        header_bar.pack_end(self.zim_menu_button)

        self._build_options_menu()

        self.tab_view = Adw.TabView()
        self.tab_view.set_vexpand(True)

        self.tab_bar = Adw.TabBar()
        self.tab_bar.set_view(self.tab_view)
        self.tab_bar.set_autohide(True)

        main_box.append(self.tab_bar)
        main_box.append(self.tab_view)

        self.tab_view.connect("notify::selected-page", self.on_selected_page_changed)
        self.add_new_tab()

    def _build_options_menu(self):
        popover_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )

        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        zoom_box.add_css_class("linked")

        btn_out = Gtk.Button(label="−")
        self.lbl_zoom = Gtk.Label(label="100%")
        self.lbl_zoom.set_size_request(60, -1)
        btn_in = Gtk.Button(label="+")

        btn_reset = Gtk.Button()
        btn_reset.set_child(self.lbl_zoom)

        btn_out.connect("clicked", lambda *_: self.on_zoom_out(None, None))
        btn_in.connect("clicked", lambda *_: self.on_zoom_in(None, None))
        btn_reset.connect("clicked", lambda *_: self.on_zoom_reset(None, None))

        zoom_box.append(btn_out)
        zoom_box.append(btn_reset)
        zoom_box.append(btn_in)
        popover_box.append(zoom_box)

        popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        btn_find_in_page = Gtk.Button(label="Find in page...", has_frame=False)
        btn_find_in_page.connect(
            "clicked",
            lambda *_: (
                self.zim_popover.popdown(),
                self.show_find_in_page(),
            ),
        )

        btn_print = Gtk.Button(label="Print", has_frame=False)
        btn_print.connect(
            "clicked", lambda *_: (self.zim_popover.popdown(), self.on_print_page(None, None))
        )

        popover_box.append(btn_find_in_page)
        popover_box.append(btn_print)
        popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        btn_main = Gtk.Button(label="Main page", has_frame=False)
        btn_main.connect(
            "clicked", lambda *_: (self.zim_popover.popdown(), self.on_go_main_page(None, None))
        )

        popover_box.append(btn_main)
        self.zim_popover.set_child(popover_box)

    def show_find_in_page(self):
        zim_page = self._current_zim_page()
        if zim_page:
            zim_page.show_search_bar()

    def update_zoom_display(self):
        webview = self._current_webview()
        if webview:
            level = int(webview.get_zoom_level() * 100)
            self.lbl_zoom.set_text(f"{level}%")

    def _make_home_page(self):
        home_page = HomePageView()
        home_page.connect("open-zim", self.on_open_zim_file)
        home_page.connect("history-clicked", self.on_history_clicked)
        home_page.connect("bookmarks-clicked", self.on_bookmarks_clicked)
        home_page.connect("search-clicked", self.on_search_clicked)
        return home_page

    def add_new_tab(self):
        home_page = self._make_home_page()
        page = self.tab_view.append(home_page)
        page.set_title("Home")
        page.set_icon(Gio.ThemedIcon.new("user-home-symbolic"))
        self.tab_view.set_selected_page(page)

    def _replace_current_tab(self, new_child, title, icon):
        old_page = self.tab_view.get_selected_page()
        if old_page is not None:
            position = self.tab_view.get_page_position(old_page)
            new_page = self.tab_view.insert(new_child, position)
        else:
            new_page = self.tab_view.append(new_child)

        new_page.set_title(title)
        new_page.set_icon(icon)
        self.tab_view.set_selected_page(new_page)

        if old_page is not None:
            self.tab_view.close_page(old_page)

        return new_page

    def on_home_clicked(self, button):
        self._replace_current_tab(
            self._make_home_page(), "Home", Gio.ThemedIcon.new("user-home-symbolic")
        )
        self._update_nav_buttons()

    def on_new_tab_clicked(self, button):
        self.add_new_tab()

    def close_current_tab(self):
        current_page = self.tab_view.get_selected_page()
        if current_page is None:
            return
        if self.tab_view.get_n_pages() <= 1:
            self.on_home_clicked(None)
            return
        self.tab_view.close_page(current_page)

    def on_open_zim_file(self, home_page, zim_path, target_uri="", new_tab=False):
        if target_uri:
            entry_path = _zim_uri_entry_path(target_uri)
            existing_tab = self._find_tab_showing_page(zim_path, entry_path)
            if existing_tab:
                self.tab_view.set_selected_page(existing_tab)
                return

        current_zim_page = self._current_zim_page()
        if not new_tab and current_zim_page and current_zim_page.zim_path == zim_path:
            load_uri = target_uri if target_uri else f"zim://{current_zim_page.archive_id}/"
            current_zim_page.webview.load_uri(load_uri)
            return

        zim_page = ZimPageView(zim_path, window_ref=self, target_uri=target_uri)
        icon = zim_page.icon or Gio.ThemedIcon.new("book-open-symbolic")

        if new_tab:
            page = self.tab_view.append(zim_page)
            page.set_title(zim_page.title)
            page.set_icon(icon)
            self.tab_view.set_selected_page(page)
        else:
            page = self._replace_current_tab(zim_page, zim_page.title, icon)

        webview = getattr(zim_page, "webview", None)
        if webview is not None:
            webview.connect("notify::title", self._on_zim_title_changed, page, zim_page)
            webview.connect("notify::uri", lambda *_: self._update_top_bookmark_button())
            webview.connect("load-changed", self._on_zim_load_changed, zim_page)
            webview.connect("decide-policy", self._on_decide_policy, zim_page)

        self._update_top_bookmark_button()

    def on_history_clicked(self, home_page, zim_path):
        title, _ = get_zim_archive_metadata(zim_path)

        dialog = Adw.Dialog()
        dialog.set_content_width(450)
        dialog.set_content_height(400)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(Adw.WindowTitle(title="History", subtitle=title))
        toolbar_view.add_top_bar(header_bar)

        clear_btn = Gtk.Button(icon_name="user-trash-symbolic")
        clear_btn.add_css_class("flat")
        clear_btn.set_tooltip_text("Clear All History")
        header_bar.pack_end(clear_btn)

        stack = Gtk.Stack()
        stack.set_vexpand(True)

        empty_status = Adw.StatusPage(
            title="No History",
            description="Pages you visit in this archive will appear here.",
            icon_name="document-open-recent-symbolic",
        )
        stack.add_named(empty_status, "empty")

        scroll = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        group = Adw.PreferencesGroup(title="Recently Visited")
        clamp.set_child(group)
        scroll.set_child(clamp)

        stack.add_named(scroll, "list")

        row_map = {}

        def refresh_visibility():
            clear_btn.set_visible(bool(row_map))
            stack.set_visible_child_name("list" if row_map else "empty")

        def remove_row(uri):
            remove_history_entry(zim_path, uri)
            row = row_map.pop(uri, None)
            if row is not None:
                group.remove(row)
            refresh_visibility()

        for uri, page_title in get_history(zim_path):
            row = Adw.ActionRow(title=page_title)
            row.add_prefix(Gtk.Image.new_from_icon_name("document-open-recent-symbolic"))
            row.set_activatable(True)
            row.connect(
                "activated",
                lambda r, u=uri: (
                    dialog.close(),
                    self.on_open_zim_file(None, zim_path, target_uri=u),
                ),
            )

            delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
            delete_btn.add_css_class("flat")
            delete_btn.set_valign(Gtk.Align.CENTER)
            delete_btn.set_tooltip_text("Remove")
            delete_btn.connect("clicked", lambda b, u=uri: remove_row(u))

            row.add_suffix(delete_btn)
            group.add(row)
            row_map[uri] = row

        refresh_visibility()

        clear_btn.connect("clicked", lambda _: (
            clear_history(zim_path),
            [group.remove(r) for r in list(row_map.values())],
            row_map.clear(),
            refresh_visibility()
        ))

        toolbar_view.set_content(stack)
        dialog.set_child(toolbar_view)
        dialog.present(self)

    def on_bookmarks_clicked(self, home_page, zim_path):
        title, _ = get_zim_archive_metadata(zim_path)

        dialog = Adw.Dialog()
        dialog.set_content_width(450)
        dialog.set_content_height(400)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(Adw.WindowTitle(title="Bookmarks", subtitle=title))
        toolbar_view.add_top_bar(header_bar)

        stack = Gtk.Stack()
        stack.set_vexpand(True)

        empty_status = Adw.StatusPage(
            title="No Bookmarks",
            description="Click the bookmark icon in the top bar while reading to save pages here.",
            icon_name=BOOKMARK_ICON_OUTLINE,
        )
        stack.add_named(empty_status, "empty")

        scroll = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        group = Adw.PreferencesGroup(title="Saved Pages")
        clamp.set_child(group)
        scroll.set_child(clamp)

        stack.add_named(scroll, "list")

        row_map = {}

        def refresh_visibility():
            stack.set_visible_child_name("list" if row_map else "empty")

        def remove_row(uri):
            toggle_bookmark(zim_path, uri, "")
            row = row_map.pop(uri, None)
            if row is not None:
                group.remove(row)
            refresh_visibility()
            self._update_top_bookmark_button()

        for uri, page_title in get_bookmarks(zim_path).items():
            row = Adw.ActionRow(title=page_title)
            row.add_prefix(Gtk.Image.new_from_icon_name(BOOKMARK_ICON_FILLED))
            row.set_activatable(True)
            row.connect(
                "activated",
                lambda r, u=uri: (
                    dialog.close(),
                    self.on_open_zim_file(None, zim_path, target_uri=u),
                ),
            )

            delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
            delete_btn.add_css_class("flat")
            delete_btn.set_valign(Gtk.Align.CENTER)
            delete_btn.set_tooltip_text("Remove Bookmark")
            delete_btn.connect("clicked", lambda b, u=uri: remove_row(u))

            row.add_suffix(delete_btn)
            group.add(row)
            row_map[uri] = row

        refresh_visibility()

        toolbar_view.set_content(stack)
        dialog.set_child(toolbar_view)
        dialog.present(self)

    def on_search_clicked(self, home_page, zim_path):
        archive_title, _ = get_zim_archive_metadata(zim_path)

        try:
            archive_id, archive = register_zim_archive(zim_path)
        except Exception as exc:
            status = Adw.StatusPage(
                title="Couldn't Open Archive",
                description=str(exc),
                icon_name="dialog-error-symbolic",
            )
            error_toolbar = Adw.ToolbarView()
            error_header = Adw.HeaderBar()
            error_header.set_title_widget(Adw.WindowTitle(title="Search Articles"))
            error_toolbar.add_top_bar(error_header)
            error_toolbar.set_content(status)

            error_dialog = Adw.Dialog()
            error_dialog.set_content_width(400)
            error_dialog.set_content_height(280)
            error_dialog.set_child(error_toolbar)
            error_dialog.present(self)
            return

        dialog = Adw.Dialog()
        dialog.set_content_width(480)
        dialog.set_content_height(560)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(
            Adw.WindowTitle(title="Search Articles", subtitle=archive_title)
        )
        toolbar_view.add_top_bar(header_bar)

        content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Search articles in archive…")
        content_box.append(search_entry)

        stack = Gtk.Stack()
        stack.set_vexpand(True)
        content_box.append(stack)

        prompt_status = Adw.StatusPage(
            title="Search this Archive",
            description="Type to search article titles and text.",
            icon_name="system-search-symbolic",
        )
        stack.add_named(prompt_status, "prompt")

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_vexpand(True)

        results_clamp = Adw.Clamp()
        results_group = Adw.PreferencesGroup(title="Results")
        results_clamp.set_child(results_group)
        results_scroll.set_child(results_clamp)

        stack.add_named(results_scroll, "results")
        stack.set_visible_child_name("prompt")
        result_rows = []

        def clear_results():
            for row in result_rows:
                results_group.remove(row)
            result_rows.clear()

        def run_search(*_args):
            query_text = search_entry.get_text().strip()
            clear_results()

            if not query_text:
                stack.set_visible_child_name("prompt")
                return

            paths = []
            try:
                searcher = Searcher(archive)
                query = Query().set_query(query_text)
                search = searcher.search(query)
                try:
                    match_count = search.getEstimatedMatches()
                except Exception:
                    match_count = 30
                match_count = min(match_count, 30) if match_count else 0
                if match_count:
                    paths = list(search.getResults(0, match_count))
            except Exception:
                paths = []

            if not paths:
                stack.set_visible_child_name("prompt")
                prompt_status.set_title("No Results")
                prompt_status.set_description(f"No articles matched “{query_text}”.")
                prompt_status.set_icon_name("edit-find-symbolic")
                return

            for path in paths:
                try:
                    entry = archive.get_entry_by_path(path)
                    entry_title = entry.title or path
                except Exception:
                    entry_title = path

                row = Adw.ActionRow(title=entry_title)
                row.add_prefix(Gtk.Image.new_from_icon_name("text-x-generic-symbolic"))
                row.set_activatable(True)

                target = f"zim://{archive_id}/{path}"
                row.connect(
                    "activated",
                    lambda r, u=target: (
                        dialog.close(),
                        self.on_open_zim_file(None, zim_path, target_uri=u),
                    ),
                )

                results_group.add(row)
                result_rows.append(row)

            stack.set_visible_child_name("results")

        search_entry.connect("search-changed", run_search)
        search_entry.connect("activate", run_search)

        toolbar_view.set_content(content_box)
        dialog.set_child(toolbar_view)
        dialog.present(self)
        search_entry.grab_focus()

    def _on_zim_title_changed(self, webview, _pspec, page, zim_page):
        title = webview.get_title()
        if title:
            page.set_title(title)
            uri = webview.get_uri()
            if uri:
                update_history_title(zim_page.zim_path, uri, title)
        self._update_top_bookmark_button()

    def _on_zim_load_changed(self, webview, load_event, zim_page):
        self._update_nav_buttons()
        if load_event == WebKit.LoadEvent.FINISHED:
            zim_page.initial_load_done = True
            uri = webview.get_uri()
            if uri:
                add_history_entry(zim_page.zim_path, uri, webview.get_title() or uri)

    def _prompt_external_browser(self, target_uri):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Open in Default Browser?",
            body=f"HTML links cannot be displayed inside the application.\n\nDo you want to open this page in your web browser?\n\nURL: {target_uri}",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("open", "Open Browser")
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dlg, response_id):
            if response_id == "open":
                try:
                    Gtk.show_uri(self, target_uri, Gdk.CURRENT_TIME)
                except Exception as e:
                    print(f"Failed to launch default browser: {e}")

        dialog.connect("response", on_response)
        dialog.present()

    def _on_decide_policy(self, webview, decision, decision_type, zim_page):
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False

        nav_action = decision.get_navigation_action()
        if nav_action.get_mouse_button() == 2:
            decision.ignore()
            return True

        if not zim_page.initial_load_done:
            return False

        try:
            request = nav_action.get_request()
            target_uri = request.get_uri()
        except Exception:
            return False

        if not target_uri:
            return False

        parsed = urllib.parse.urlparse(target_uri)
        is_html = (
            parsed.path.lower().endswith(".html")
            or parsed.path.lower().endswith(".htm")
            or not target_uri.startswith("zim://")
        )

        if is_html:
            decision.ignore()
            self._prompt_external_browser(target_uri)
            return True

        entry_path = _zim_uri_entry_path(target_uri)
        match_page = self._find_tab_showing_page(
            zim_page.zim_path, entry_path, exclude_zim_page=zim_page
        )
        if match_page is not None:
            decision.ignore()
            self.tab_view.set_selected_page(match_page)
            return True

        return False

    def _find_tab_showing_page(self, zim_path, entry_path, exclude_zim_page=None):
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            child = page.get_child()
            if not isinstance(child, ZimPageView) or child is exclude_zim_page:
                continue
            if child.zim_path != zim_path:
                continue

            webview = getattr(child, "webview", None)
            current_uri = webview.get_uri() if webview else None
            if current_uri and _zim_uri_entry_path(current_uri) == entry_path:
                return page
        return None

    def on_selected_page_changed(self, tab_view, _pspec):
        self._update_nav_buttons()
        self._update_top_bookmark_button()
        self.update_zoom_display()

    def _current_zim_page(self):
        page = self.tab_view.get_selected_page()
        if page is None:
            return None
        child = page.get_child()
        return child if isinstance(child, ZimPageView) else None

    def _current_webview(self):
        zim_page = self._current_zim_page()
        return getattr(zim_page, "webview", None) if zim_page else None

    def _update_top_bookmark_button(self):
        zim_page = self._current_zim_page()
        if zim_page is None:
            self.bookmark_top_btn.set_visible(False)
            self.zim_menu_button.set_visible(False)
            return

        self.bookmark_top_btn.set_visible(True)
        self.zim_menu_button.set_visible(True)

        webview = zim_page.webview
        uri = webview.get_uri() if webview else None
        if uri and is_bookmarked(zim_page.zim_path, uri):
            self.bookmark_top_btn.set_icon_name(BOOKMARK_ICON_FILLED)
            self.bookmark_top_btn.set_tooltip_text("Remove Bookmark")
        else:
            self.bookmark_top_btn.set_icon_name(BOOKMARK_ICON_OUTLINE)
            self.bookmark_top_btn.set_tooltip_text("Bookmark Page")

    def on_top_bookmark_clicked(self, button):
        zim_page = self._current_zim_page()
        if not zim_page or not zim_page.webview:
            return

        uri = zim_page.webview.get_uri()
        title = zim_page.webview.get_title() or uri
        if uri:
            toggle_bookmark(zim_page.zim_path, uri, title)
            self._update_top_bookmark_button()

    def _update_nav_buttons(self):
        page = self.tab_view.get_selected_page()
        child = page.get_child() if page else None
        is_home = isinstance(child, HomePageView)

        self.home_button.set_sensitive(not is_home)

        webview = self._current_webview()
        if webview is None:
            self.back_button.set_sensitive(False)
            self.forward_button.set_sensitive(False)
            return

        self.back_button.set_sensitive(webview.can_go_back())
        self.forward_button.set_sensitive(webview.can_go_forward())

    def on_back_clicked(self, button):
        webview = self._current_webview()
        if webview is not None and webview.can_go_back():
            webview.go_back()

    def on_forward_clicked(self, button):
        webview = self._current_webview()
        if webview is not None and webview.can_go_forward():
            webview.go_forward()

    def on_zoom_in(self, action, param):
        webview = self._current_webview()
        if webview is not None:
            webview.set_zoom_level(min(webview.get_zoom_level() + 0.1, 5.0))
            self.update_zoom_display()

    def on_zoom_out(self, action, param):
        webview = self._current_webview()
        if webview is not None:
            webview.set_zoom_level(max(webview.get_zoom_level() - 0.1, 0.2))
            self.update_zoom_display()

    def on_zoom_reset(self, action, param):
        webview = self._current_webview()
        if webview is not None:
            webview.set_zoom_level(1.0)
            self.update_zoom_display()

    def on_print_page(self, action, param):
        webview = self._current_webview()
        if webview is not None:
            WebKit.PrintOperation.new(webview).run_dialog(self)

    def on_go_main_page(self, action, param):
        zim_page = self._current_zim_page()
        if zim_page is not None and zim_page.archive_id:
            zim_page.webview.load_uri(f"zim://{zim_page.archive_id}/")


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
        if _save_state["scheduled"]:
            _write_persisted_state()
        Adw.Application.do_shutdown(self)

    def on_close_tab(self, action, param):
        win = self.get_active_window()
        if win:
            win.close_current_tab()

    def on_find_in_page(self, action, param):
        win = self.get_active_window()
        if win:
            win.show_find_in_page()


def main(version=None):
    app = WebArchivesApp()
    sys.argv[0] = str(Path(sys.argv[0]).resolve())
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
