import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from .downloads import (
    DownloadManager,
    STATUS_QUEUED,
    STATUS_DOWNLOADING,
    STATUS_PAUSED,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from .state import format_byte_size, resolve_display_path


class DownloadsDialog(Adw.Dialog):
    def __init__(self):
        super().__init__()
        self.set_title("Downloads")
        self.set_content_width(500)
        self.set_content_height(600)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(Adw.WindowTitle(title="Downloads"))
        toolbar_view.add_top_bar(header_bar)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)

        self.empty_status = Adw.StatusPage(
            title="No Downloads",
            description="ZIM files you download from the Kiwix library will show up here — "
                        "you can pause and resume them any time, even after restarting the app.",
            icon_name="folder-download-symbolic",
        )
        self.stack.add_named(self.empty_status, "empty")

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        clamp = Adw.Clamp(margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.group = Adw.PreferencesGroup()
        clamp.set_child(self.group)
        scroll.set_child(clamp)
        self.stack.add_named(scroll, "list")

        toolbar_view.set_content(self.stack)
        self.set_child(toolbar_view)

        self.manager = DownloadManager.get()
        self._rows = {}
        self._changed_id = self.manager.connect("download-changed", self._on_changed)
        self._removed_id = self.manager.connect("download-removed", self._on_removed)
        self.connect("closed", self._on_closed)

        self._rebuild()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_closed(self, *_args):
        self.manager.disconnect(self._changed_id)
        self.manager.disconnect(self._removed_id)

    def _rebuild(self):
        for entry in list(self._rows.values()):
            self.group.remove(entry["row"])
        self._rows.clear()
        for rec in self.manager.list_downloads():
            self._add_or_update_row(rec["id"])
        self._update_stack_visibility()

    def _update_stack_visibility(self):
        self.stack.set_visible_child_name("list" if self._rows else "empty")

    def _on_changed(self, manager, download_id):
        self._add_or_update_row(download_id)
        self._update_stack_visibility()

    def _on_removed(self, manager, download_id):
        entry = self._rows.pop(download_id, None)
        if entry is not None:
            self.group.remove(entry["row"])
        self._update_stack_visibility()

    def _add_or_update_row(self, download_id):
        rec = self.manager.get_download(download_id)
        if rec is None:
            return

        entry = self._rows.get(download_id)
        if entry is None:
            row = Adw.ActionRow()
            row.add_prefix(Gtk.Image.new_from_icon_name("folder-download-symbolic"))

            progress = Gtk.ProgressBar()
            progress.set_valign(Gtk.Align.CENTER)
            progress.set_size_request(90, -1)
            progress.set_show_text(True)

            action_btn = Gtk.Button()
            action_btn.add_css_class("flat")
            action_btn.add_css_class("circular")
            action_btn.set_valign(Gtk.Align.CENTER)
            action_btn.connect("clicked", self._on_action_clicked, download_id)

            remove_btn = Gtk.Button(icon_name="user-trash-symbolic")
            remove_btn.add_css_class("flat")
            remove_btn.add_css_class("circular")
            remove_btn.set_valign(Gtk.Align.CENTER)
            remove_btn.set_tooltip_text("Remove")
            remove_btn.connect(
                "clicked", lambda b, did=download_id: self.manager.cancel_download(did)
            )

            row.add_suffix(progress)
            row.add_suffix(action_btn)
            row.add_suffix(remove_btn)

            self.group.add(row)
            entry = {
                "row": row,
                "progress": progress,
                "action_btn": action_btn,
                "remove_btn": remove_btn,
            }
            self._rows[download_id] = entry

        self._refresh_row(entry, rec)

    def _refresh_row(self, entry, rec):
        status = rec.get("status")
        downloaded = rec.get("downloaded_bytes") or 0
        total = rec.get("total_bytes")

        row = entry["row"]
        progress = entry["progress"]
        action_btn = entry["action_btn"]

        row.set_title(rec.get("title") or rec.get("target_path", "Download"))

        fraction = min(downloaded / total, 1.0) if total else 0.0
        size_bit = (
            f"{format_byte_size(downloaded)} of {format_byte_size(total)}"
            if total else format_byte_size(downloaded)
        )

        if status in (STATUS_QUEUED, STATUS_DOWNLOADING):
            row.set_subtitle("Downloading…" if status == STATUS_DOWNLOADING else "Waiting…")
            progress.set_visible(True)
            progress.set_fraction(fraction)
            progress.set_text(f"{int(fraction * 100)}%" if total else size_bit)
            action_btn.set_icon_name("media-playback-pause-symbolic")
            action_btn.set_tooltip_text("Pause")
            action_btn.set_sensitive(True)
        elif status == STATUS_PAUSED:
            row.set_subtitle(f"Paused — {size_bit}")
            progress.set_visible(True)
            progress.set_fraction(fraction)
            progress.set_text(f"{int(fraction * 100)}%" if total else size_bit)
            action_btn.set_icon_name("media-playback-start-symbolic")
            action_btn.set_tooltip_text("Resume")
            action_btn.set_sensitive(True)
        elif status == STATUS_COMPLETED:
            row.set_subtitle(f"Downloaded — {format_byte_size(total or downloaded)}")
            progress.set_visible(False)
            action_btn.set_icon_name("checkbox-checked-symbolic")
            action_btn.set_tooltip_text(
                f"Saved to {resolve_display_path(rec.get('target_path', ''))}"
            )
            action_btn.set_sensitive(False)
        elif status == STATUS_FAILED:
            row.set_subtitle(f"Failed — {rec.get('error') or 'Unknown error'}")
            progress.set_visible(False)
            action_btn.set_icon_name("view-refresh-symbolic")
            action_btn.set_tooltip_text("Retry")
            action_btn.set_sensitive(True)

    def _on_action_clicked(self, button, download_id):
        rec = self.manager.get_download(download_id)
        if not rec:
            return
        status = rec.get("status")
        if status in (STATUS_QUEUED, STATUS_DOWNLOADING):
            self.manager.pause_download(download_id)
        elif status in (STATUS_PAUSED, STATUS_FAILED):
            self.manager.resume_download(download_id)
