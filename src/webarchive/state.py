import json
import os
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import gi
gi.require_version("WebKit", "6.0")
from gi.repository import GLib, Gio, WebKit

from libzim.reader import Archive
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

save_state = {"scheduled": False}


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


def write_persisted_state():
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
    if save_state["scheduled"]:
        return
    save_state["scheduled"] = True

    def _do_save():
        save_state["scheduled"] = False
        write_persisted_state()
        return False

    GLib.timeout_add(500, _do_save)


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


def zim_uri_entry_path(uri):
    parsed = urllib.parse.urlparse(uri)
    return urllib.parse.unquote(parsed.path.lstrip("/"))


def handle_zim_uri_scheme(request):
    uri = request.get_uri()
    parsed = urllib.parse.urlparse(uri)
    archive_id = parsed.netloc
    entry_path = zim_uri_entry_path(uri)

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


def describe_download_error(exc):
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
