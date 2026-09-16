import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from .state import get_show_welcome, set_show_welcome
FEATURES = [
    (
        "network-server-symbolic",
        "Browse the Kiwix Library",
        "Search thousands of free ZIM archives — Wikipedia, TED Talks,and download the ones you want.",
    ),
    (
        "system-search-symbolic",
        "Full-text search",
        "Search inside any archive to find articles instantly — all "
        "completely offline.",
    ),
    (
        "user-bookmarks-symbolic",
        "Bookmarks & History",
        "Save pages you care about and pick up where you left off in "
        "any archive.",
    ),
]


class WelcomeDialog(Adw.Dialog):
    def __init__(self):
        super().__init__()
        self.set_title("Welcome to Web Archives")
        self.set_content_width(480)
        self.set_content_height(600)

        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(Adw.WindowTitle(title="Welcome to Web Archives"))
        toolbar_view.add_top_bar(header_bar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        clamp = Adw.Clamp(margin_top=16, margin_bottom=16, margin_start=24, margin_end=24)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)
        title = Gtk.Label(label="Your Offline Knowledge Library")
        title.add_css_class("title-1")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_halign(Gtk.Align.CENTER)
        box.append(title)

        subtitle = Gtk.Label(
            label=(
                "Web Archives lets you download whole websites as ZIM files "
                "and read them anytime — even with no internet connection."
            )
        )
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.set_halign(Gtk.Align.CENTER)
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        giure_group = Adw.PreferencesGroup()
        for icon_name, feat_title, feat_desc in FEATURES:
            row = Adw.ActionRow(title=feat_title, subtitle=feat_desc)
            row.set_title_lines(1)
            row.set_subtitle_lines(3)
            prefix_icon = Gtk.Image.new_from_icon_name(icon_name)
            prefix_icon.set_pixel_size(20)
            row.add_prefix(prefix_icon)
            feature_group.add(row)
        box.append(feature_group)

        toolbar_view.set_content(scroll)

        bottom_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=8,
            margin_bottom=16,
            margin_start=24,
            margin_end=24,
        )

        self.dont_show_check = Gtk.CheckButton(label="Don't show this again")
        self.dont_show_check.set_halign(Gtk.Align.CENTER)
        bottom_box.append(self.dont_show_check)

        start_btn = Gtk.Button(label="Get Started")
        start_btn.add_css_class("suggested-action")
        start_btn.add_css_class("pill")
        start_btn.set_halign(Gtk.Align.CENTER)
        start_btn.connect("clicked", self._on_get_started)
        bottom_box.append(start_btn)

        toolbar_view.add_bottom_bar(bottom_box)
        self.set_child(toolbar_view)

    def _on_get_started(self, button):
        if self.dont_show_check.get_active():
            set_show_welcome(False)
        self.close()


def maybe_show_welcome(parent_window):
    if not get_show_welcome():
        return

    def _present():
        WelcomeDialog().present(parent_window)
        return False

    GLib.idle_add(_present)
