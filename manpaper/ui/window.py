from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from .preferences import PreferencesWindow
from .factories import (
    create_recode_popover_factory, 
    create_download_popover_factory, 
    create_online_item_factory,
    create_wallpaper_item_factory
)

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Manpaper', default_width=800, default_height=600)
        self.app = app
        self.set_size_request(628, 400)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)

        self.view_stack = Adw.ViewStack(enable_transitions=True, transition_duration=300)
        self.title_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_UP_DOWN, transition_duration=300)

        content = Adw.ToolbarView()
        content.add_css_class("main-content")

        header = Adw.HeaderBar(title_widget=self.title_stack)
        self.header_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=250, reveal_child=True)
        self.header_revealer.set_child(header)
        content.add_top_bar(self.header_revealer)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search wallpapers...")
        self.search_entry.connect("search-changed", self.app._on_search_changed)
        self.search_entry.connect("activate", self.app._on_search_activated)

        view_switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.title_stack.add_named(view_switcher, "switcher")
        self.title_stack.add_named(self.search_entry, "search")

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Search")
        self.search_button.connect("toggled", self.app._on_search_toggled)
        
        self.search_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=300)
        self.search_button_revealer.set_child(self.search_button)
        self.search_button_revealer.set_reveal_child(True)
        header.pack_start(self.search_button_revealer)

        self.recode_spinner = Adw.Spinner()
        self.recode_button = Gtk.MenuButton(child=self.recode_spinner, tooltip_text="recoding progress")
        
        recode_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=300, reveal_child=False)
        recode_revealer.set_child(self.recode_button)
        
        self.recode_revealer_container = Gtk.Box()
        self.recode_revealer_container.append(recode_revealer)
        self.recode_revealer_container.set_visible(False)
        
        recode_popover = Gtk.Popover()
        self.recode_button.set_popover(recode_popover)
        
        scrolled_list_maxh = 300

        popover_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_vbox.set_size_request(350, scrolled_list_maxh)
        recode_popover.set_child(popover_vbox)

        popover_list_view = Gtk.ListView.new(Gtk.SingleSelection.new(self.app.recode_popover_store), create_recode_popover_factory(self.app))
        popover_list_view.add_css_class("recode-popover-list")

        scrolled_list = Gtk.ScrolledWindow(child=popover_list_view, vexpand=True, max_content_height=scrolled_list_maxh, hscrollbar_policy=Gtk.PolicyType.NEVER)
        popover_vbox.append(scrolled_list)
        scrolled_list.add_css_class("scrolled-list")

        stop_all_button = Gtk.Button(label="Stop All", margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        stop_all_button.add_css_class("destructive-action")
        stop_all_button.connect('clicked', self.app._on_stop_all_recodes_clicked)
        popover_vbox.append(stop_all_button)
        
        header.pack_end(self.recode_revealer_container)

        self.download_spinner = Adw.Spinner()
        self.download_button = Gtk.MenuButton(child=self.download_spinner, tooltip_text="download progress")
        
        download_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=300, reveal_child=False)
        download_revealer.set_child(self.download_button)
        
        self.download_revealer_container = Gtk.Box()
        self.download_revealer_container.append(download_revealer)
        self.download_revealer_container.set_visible(False)
        
        download_popover = Gtk.Popover()
        self.download_button.set_popover(download_popover)
        
        download_popover_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        download_popover_vbox.set_size_request(350, scrolled_list_maxh)
        download_popover.set_child(download_popover_vbox)

        download_popover_list_view = Gtk.ListView.new(Gtk.SingleSelection.new(self.app.download_popover_store), create_download_popover_factory(self.app))
        download_popover_list_view.add_css_class("download-popover-list")

        download_scrolled_list = Gtk.ScrolledWindow(child=download_popover_list_view, vexpand=True, max_content_height=scrolled_list_maxh, hscrollbar_policy=Gtk.PolicyType.NEVER)
        download_popover_vbox.append(download_scrolled_list)
        download_scrolled_list.add_css_class("scrolled-list")

        stop_all_downloads_button = Gtk.Button(label="Stop All", margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        stop_all_downloads_button.add_css_class("destructive-action")
        stop_all_downloads_button.connect('clicked', self.app._on_stop_all_downloads_clicked)
        download_popover_vbox.append(stop_all_downloads_button)
        
        header.pack_end(self.download_revealer_container)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        self.menu_popover = Gtk.PopoverMenu()
        menu_button.set_popover(self.menu_popover)
        header.pack_end(menu_button)

        self.static_view = self._create_grid_view(self.app.static_model)
        static_page = self.view_stack.add_titled(self._create_scrolled_window(self.static_view), 'static', 'Static')
        static_page.set_icon_name('image-x-generic-symbolic')

        self.live_view = self._create_grid_view(self.app.live_model)
        live_page = self.view_stack.add_titled(self._create_scrolled_window(self.live_view), 'live', 'Live')
        live_page.set_icon_name('video-x-generic-symbolic')

        online_page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Create a container for the filter toggles
        online_filters_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)

        # Purity toggles
        purity_label = Gtk.Label(label="Purity", halign=Gtk.Align.START, margin_start=6)
        online_filters_box.append(purity_label)
        purity_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        purity_box.add_css_class("linked")
        self.sfw_switch = Gtk.ToggleButton(label="SFW")
        self.sketchy_switch = Gtk.ToggleButton(label="Sketchy")
        self.nsfw_switch = Gtk.ToggleButton(label="NSFW")

        purity_box.append(self.sfw_switch)
        purity_box.append(self.sketchy_switch)
        purity_box.append(self.nsfw_switch)
        online_filters_box.append(purity_box)

        # Category toggles
        category_label = Gtk.Label(label="Categories", halign=Gtk.Align.START, margin_start=6)
        online_filters_box.append(category_label)
        category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        category_box.add_css_class("linked")
        self.general_switch = Gtk.ToggleButton(label="General")
        self.anime_switch = Gtk.ToggleButton(label="Anime")
        self.people_switch = Gtk.ToggleButton(label="People")

        category_box.append(self.general_switch)
        category_box.append(self.anime_switch)
        category_box.append(self.people_switch)
        online_filters_box.append(category_box)

        # Resolution filter
        row_resolution = Adw.EntryRow(title="Resolution")
        row_resolution.set_text(self.app.settings.get_string('wallhaven-resolution'))
        row_resolution.connect('changed', self.app._on_resolution_changed)
        online_filters_box.append(row_resolution)

        # Atleast (minimum resolution) filter
        row_atleast = Adw.EntryRow(title="Minimum Resolution")
        row_atleast.set_text(self.app.settings.get_string('wallhaven-atleast'))
        row_atleast.connect('changed', self.app._on_atleast_changed)
        online_filters_box.append(row_atleast)

        # Aspect Ratio filter
        row_ratio = Adw.EntryRow(title="Aspect Ratio")
        row_ratio.set_text(self.app.settings.get_string('wallhaven-ratios'))
        row_ratio.connect('changed', self.app._on_ratio_changed)
        online_filters_box.append(row_ratio)

        self.sfw_switch.set_active(self.app.settings.get_boolean('wallhaven-purity-sfw'))
        self.sketchy_switch.set_active(self.app.settings.get_boolean('wallhaven-purity-sketchy'))
        self.nsfw_switch.set_active(self.app.settings.get_boolean('wallhaven-purity-nsfw'))
        self.general_switch.set_active(self.app.settings.get_boolean('wallhaven-category-general'))
        self.anime_switch.set_active(self.app.settings.get_boolean('wallhaven-category-anime'))
        self.people_switch.set_active(self.app.settings.get_boolean('wallhaven-category-people'))

        self.sfw_switch.connect("toggled", self.app._on_purity_toggled, "sfw")
        self.sketchy_switch.connect("toggled", self.app._on_purity_toggled, "sketchy")
        self.nsfw_switch.connect("toggled", self.app._on_purity_toggled, "nsfw")
        self.general_switch.connect("toggled", self.app._on_category_toggled, "general")
        self.anime_switch.connect("toggled", self.app._on_category_toggled, "anime")
        self.people_switch.connect("toggled", self.app._on_category_toggled, "people")

        self.online_view = self._create_grid_view(self.app.online_model, create_online_item_factory(self.app))
        scrolled_online_view = self._create_scrolled_window(self.online_view)
        scrolled_online_view.set_vexpand(True)
        online_page_box.append(scrolled_online_view)

        self.load_more_button = Gtk.Button(label="Load More")
        self.load_more_button.add_css_class("pill")
        self.load_more_button.add_css_class("suggested-action")
        self.load_more_button.set_halign(Gtk.Align.CENTER)
        online_page = self.view_stack.add_titled(online_page_box, 'online', 'Online')
        online_page.set_icon_name('globe-symbolic')

        self.load_more_button = Gtk.Button(label="Load More")
        self.load_more_button.add_css_class("pill")
        self.load_more_button.add_css_class("suggested-action")
        self.load_more_button.connect("clicked", self.app._on_load_more_online_wallpapers_clicked)

        self.load_more_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=300, reveal_child=False, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=24)
        self.load_more_button_revealer.set_child(self.load_more_button)
        self.load_more_button_revealer.add_css_class("pill-revealer")

        prefs_view = self.app.prefs_window.create_preferences_view()
        prefs_page = self.view_stack.add_titled(prefs_view, 'preferences', 'Config')
        prefs_page.set_icon_name('preferences-system-symbolic')

        view_switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)
        self.slide_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=250)
        self.slide_revealer.set_child(view_switcher_bar)
        
        self.bottom_bar_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.bottom_bar_container.append(self.slide_revealer)

        self.fade_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=500)
        self.fade_revealer.set_child(self.bottom_bar_container)
        content.add_bottom_bar(self.fade_revealer)

        self.random_button = Gtk.Button(tooltip_text="Set a random wallpaper from the current view")
        self.random_button.connect('clicked', self.app._on_random_button_clicked)
        button_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_content.append(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        button_content.append(Gtk.Label(label="Random"))
        self.random_button.set_child(button_content)
        self.random_button.add_css_class("pill")
        self.random_button.add_css_class("suggested-action")
        
        random_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=300, reveal_child=True, halign=Gtk.Align.END, valign=Gtk.Align.END, margin_bottom=24, margin_end=24)
        random_button_revealer.set_child(self.random_button)
        random_button_revealer.add_css_class("pill-revealer")
        
        self.filter_button = Gtk.MenuButton(icon_name="view-filter-symbolic", tooltip_text="Filter online wallpapers")
        self.filter_button.add_css_class("pill")
        self.filter_button.add_css_class("opaque")

        filter_popover = Gtk.Popover()
        filter_popover.set_child(online_filters_box)
        self.filter_button.set_popover(filter_popover)

        self.filter_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT, transition_duration=300, reveal_child=False, halign=Gtk.Align.START, valign=Gtk.Align.END, margin_bottom=24, margin_start=24)
        self.filter_button_revealer.set_child(self.filter_button)
        self.filter_button_revealer.add_css_class("pill-revealer")

        add_button = Gtk.MenuButton(icon_name="list-add-symbolic", tooltip_text="Add source")
        add_button.add_css_class("pill")
        add_button.add_css_class("opaque")

        add_menu = Gio.Menu()
        add_menu.append("Add from URL", "app.add_url")
        add_menu.append("Add local file", "app.add_local")
        
        addbtn_popover = Gtk.PopoverMenu()
        addbtn_popover.set_menu_model(add_menu)
        add_button.set_popover(addbtn_popover)

        self.add_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT, transition_duration=300, reveal_child=False, halign=Gtk.Align.START, valign=Gtk.Align.END, margin_bottom=24, margin_start=24)
        self.add_button_revealer.set_child(add_button)
        self.add_button_revealer.add_css_class("pill-revealer")

        self.status_page = Adw.StatusPage(icon_name="system-search-symbolic", title="No Results Found", description="Try a different search.", visible=False)

        overlay = Gtk.Overlay(vexpand=True)
        overlay.set_child(self.view_stack)
        overlay.add_overlay(self.app.spinner)
        overlay.add_overlay(self.status_page)
        overlay.add_overlay(random_button_revealer)
        overlay.add_overlay(self.add_button_revealer)
        overlay.add_overlay(self.filter_button_revealer)
        overlay.add_overlay(self.load_more_button_revealer)
        content.set_content(overlay)
        
        self.toast_overlay = Adw.ToastOverlay(child=content)
        self.set_content(self.toast_overlay)

    def _create_grid_view(self, model, factory=None):
        """Helper to create a Gtk.GridView."""
        if factory is None:
            factory = create_wallpaper_item_factory(self.app)
        view = Gtk.GridView.new(model, factory)
        view.connect('activate', self.app._on_wallpaper_activated)
        return view

    def _create_scrolled_window(self, child):
        """Helper to create a ScrolledWindow."""
        scrolled = Gtk.ScrolledWindow(child=child)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_margin_top(24)
        scrolled.set_margin_bottom(24)
        scrolled.set_margin_start(20)
        scrolled.set_margin_end(20)
        
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect("scroll", self.app._on_scroll_resize)
        scrolled.add_controller(scroll_controller)
        return scrolled
