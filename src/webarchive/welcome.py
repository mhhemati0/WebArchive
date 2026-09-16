import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk
from .state import get_show_welcome, set_show_welcome

FEATURES = [
    (
        "network-server-symbolic",
        "Browse the Kiwix Library",
        "Search thousands of free ZIM archives — Wikipedia, TED Talks, and download the ones you want.",
    ),
    (
        "user-bookmarks-symbolic",
        "Bookmarks &amp; History",
        "Save pages you care about and pick up where you left off in any archive.",
    ),
    (
        "system-search-symbolic",
        "Full-Text Search",
        "Search inside any archive to find articles instantly — all completely offline.",
    ),
]


class WelcomeDialog(Adw.Dialog):

    def __init__(self):
        super().__init__()
        self.set_title("Welcome")
        self.set_content_width(500)
        self.set_content_height(600)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_show_title(False)
        toolbar_view.add_top_bar(header_bar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        clamp = Adw.Clamp(
            maximum_size=420,
            margin_top=24,
            margin_bottom=32,
            margin_start=24,
            margin_end=24,
        )
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        clamp.set_child(box)

        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        app_icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
        app_icon.set_pixel_size(48)
        app_icon.add_css_class("accent")
        app_icon.set_margin_bottom(8)
        header_box.append(app_icon)

        title = Gtk.Label(label="Your Offline Knowledge Library")
        title.add_css_class("title-1")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)

        subtitle = Gtk.Label(
            label=(
                "Web Archives lets you download whole websites as ZIM files "
                "and read them anytime — even with no internet connection."
            )
        )
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("body")

        header_box.append(title)
        header_box.append(subtitle)
        box.append(header_box)

        # --- Features Group ---
        feature_group = Adw.PreferencesGroup()
        for icon_name, feat_title, feat_desc in FEATURES:
            row = Adw.ActionRow(title=feat_title, subtitle=feat_desc)
            row.set_use_markup(True)
            row.set_title_lines(1)
            row.set_subtitle_lines(3)

            prefix_icon = Gtk.Image.new_from_icon_name(icon_name)
            prefix_icon.set_pixel_size(24)
            prefix_icon.add_css_class("accent")
            row.add_prefix(prefix_icon)

            feature_group.add(row)

        box.append(feature_group)
        toolbar_view.set_content(scroll)

        # --- Bottom Action Bar ---
        bottom_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=16,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )

        start_btn = Gtk.Button(label="Get Started")
        start_btn.add_css_class("suggested-action")
        start_btn.add_css_class("pill")
        start_btn.set_size_request(200, 44)
        start_btn.set_halign(Gtk.Align.CENTER)
        start_btn.connect("clicked", self._on_get_started)
        bottom_box.append(start_btn)

        toolbar_view.add_bottom_bar(bottom_box)
        self.set_child(toolbar_view)

    def _on_get_started(self, button):
        set_show_welcome(False)
        self.close()


def maybe_show_welcome(parent_window):
    if not get_show_welcome():
        return

    def _present():
        WelcomeDialog().present(parent_window)
        return False

    GLib.idle_add(_present)
