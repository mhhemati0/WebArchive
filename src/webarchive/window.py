import urllib.parse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, Gio, WebKit, Gdk

from libzim.search import Query, Searcher

from .state import (
    BOOKMARK_ICON_FILLED,
    BOOKMARK_ICON_OUTLINE,
    zim_uri_entry_path,
    add_history_entry,
    clear_history,
    get_bookmarks,
    get_history,
    get_zim_archive_metadata,
    is_bookmarked,
    register_zim_archive,
    remove_history_entry,
    toggle_bookmark,
    update_history_title,
)
from .home import HomePageView
from .zim import ZimPageView

class WebArchivesWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(800, 600)

        self.set_size_request(360, 480)
        self.set_title("Web Archives")

        self.header_bar = header_bar = Adw.HeaderBar()

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

        self.new_tab_button = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="New Tab")
        self.new_tab_button.connect("clicked", self.on_new_tab_clicked)
        header_bar.pack_start(self.new_tab_button)

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

        self.tab_view = Adw.TabView()
        self.tab_view.set_vexpand(True)

        self.tab_bar = Adw.TabBar()
        self.tab_bar.set_view(self.tab_view)
        self.tab_bar.set_autohide(True)

        self.tab_button = Adw.TabButton()
        self.tab_button.set_view(self.tab_view)
        self.tab_button.set_action_name("overview.open")

        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.bottom_bar.set_homogeneous(True)
        self.bottom_bar.add_css_class("toolbar")
        self.bottom_bar.set_visible(False)

        self._build_options_menu()

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header_bar)
        toolbar_view.add_top_bar(self.tab_bar)
        toolbar_view.set_content(self.tab_view)
        toolbar_view.add_bottom_bar(self.bottom_bar)

        self.tab_overview = Adw.TabOverview()
        self.tab_overview.set_view(self.tab_view)
        self.tab_overview.set_enable_new_tab(True)
        self.tab_overview.connect("create-tab", self.on_tab_overview_create_tab)
        self.tab_overview.set_child(toolbar_view)

        self.set_content(self.tab_overview)

        narrow_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 500sp")
        )
        narrow_breakpoint.add_setter(self.tab_bar, "visible", False)
        narrow_breakpoint.add_setter(self.new_tab_button, "visible", False)
        narrow_breakpoint.connect("apply", self._enter_narrow_mode)
        narrow_breakpoint.connect("unapply", self._leave_narrow_mode)
        self.add_breakpoint(narrow_breakpoint)

        self.tab_view.connect("notify::selected-page", self.on_selected_page_changed)
        self.add_new_tab()

    def _enter_narrow_mode(self, breakpoint):
        self.header_bar.remove(self.home_button)
        self.header_bar.remove(self.back_button)
        self.header_bar.remove(self.forward_button)
        self.header_bar.remove(self.bookmark_top_btn)
        self.header_bar.remove(self.zim_menu_button)

        self.bottom_bar.append(self.home_button)
        self.bottom_bar.append(self.back_button)
        self.bottom_bar.append(self.forward_button)
        self.bottom_bar.append(self.tab_button)
        self.bottom_bar.append(self.bookmark_top_btn)
        self.bottom_bar.append(self.zim_menu_button)
        self.bottom_bar.set_visible(True)

    def _leave_narrow_mode(self, breakpoint):
        self.bottom_bar.remove(self.home_button)
        self.bottom_bar.remove(self.back_button)
        self.bottom_bar.remove(self.forward_button)
        self.bottom_bar.remove(self.tab_button)
        self.bottom_bar.remove(self.bookmark_top_btn)
        self.bottom_bar.remove(self.zim_menu_button)
        self.bottom_bar.set_visible(False)

        self.header_bar.remove(self.new_tab_button)

        self.header_bar.pack_start(self.home_button)
        self.header_bar.pack_start(self.back_button)
        self.header_bar.pack_start(self.forward_button)
        self.header_bar.pack_start(self.new_tab_button)
        self.header_bar.pack_start(self.bookmark_top_btn)
        self.header_bar.pack_end(self.zim_menu_button)

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
        return page

    def on_tab_overview_create_tab(self, tab_overview):
        return self.add_new_tab()

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
            entry_path = zim_uri_entry_path(target_uri)
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

        entry_path = zim_uri_entry_path(target_uri)
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
            if current_uri and zim_uri_entry_path(current_uri) == entry_path:
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
