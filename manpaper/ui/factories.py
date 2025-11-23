from gi.repository import Gtk, Pango, Gdk, GLib, Adw
from pathlib import Path
from ..data_models import OnlineWallpaperItem, WallpaperItem

def create_recode_popover_factory(app):
    """Creates a factory for items in the Recode popover ListView."""
    factory = Gtk.SignalListItemFactory()

    def setup_cb(f, list_item):
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, spacing=8, margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)
        row_box.add_css_class("recode-item")
        
        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
        main_label = Gtk.Label(halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
        status_label = Gtk.Label(halign=Gtk.Align.START)
        status_label.add_css_class("caption")
        label_box.append(main_label)
        label_box.append(status_label)
        row_box.append(label_box)

        stop_button = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
        stop_button.add_css_class("circular")
        stop_button.add_css_class("flat")
        row_box.append(stop_button)
        
        list_item.set_child(row_box)

    def bind_cb(f, list_item):
        row_box = list_item.get_child()
        label_box = row_box.get_first_child()
        main_label = label_box.get_first_child()
        status_label = label_box.get_last_child()
        stop_button = row_box.get_last_child()
        
        queue_item = list_item.get_item()
        if not queue_item: return

        main_label.set_text(queue_item.text)
        status_label.set_text(queue_item.status)
        
        if hasattr(stop_button, 'handler_id') and stop_button.handler_id > 0:
            stop_button.disconnect(stop_button.handler_id)
        stop_button.handler_id = stop_button.connect("clicked", app._on_stop_one_recode_clicked, queue_item.wallpaper_item)

    factory.connect("setup", setup_cb)
    factory.connect("bind", bind_cb)
    return factory

def create_download_popover_factory(app):
    """Creates a factory for items in the Download popover ListView."""
    factory = Gtk.SignalListItemFactory()

    def setup_cb(f, list_item):
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, spacing=8, margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)
        row_box.add_css_class("download-item")
        
        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
        main_label = Gtk.Label(halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
        status_label = Gtk.Label(halign=Gtk.Align.START)
        status_label.add_css_class("caption")
        label_box.append(main_label)
        label_box.append(status_label)
        row_box.append(label_box)

        stop_button = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
        stop_button.add_css_class("circular")
        stop_button.add_css_class("flat")
        row_box.append(stop_button)
        
        list_item.set_child(row_box)

    def bind_cb(f, list_item):
        row_box = list_item.get_child()
        label_box = row_box.get_first_child()
        main_label = label_box.get_first_child()
        status_label = label_box.get_last_child()
        stop_button = row_box.get_last_child()
        
        queue_item = list_item.get_item()
        if not queue_item: return

        main_label.set_text(queue_item.text)
        status_label.set_text(queue_item.status)
        
        if hasattr(stop_button, 'handler_id') and stop_button.handler_id > 0:
            stop_button.disconnect(stop_button.handler_id)
        stop_button.handler_id = stop_button.connect("clicked", app._on_stop_one_download_clicked, queue_item)

    factory.connect("setup", setup_cb)
    factory.connect("bind", bind_cb)
    return factory

def create_online_item_factory(app):
    """Creates a factory for items in the Online GridView."""
    factory = Gtk.SignalListItemFactory()

    def on_setup(factory, list_item):
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=300)
        item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        list_item.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        list_item.aspect_frame = Gtk.AspectFrame(xalign=0.5, yalign=0.5, obey_child=False)
        list_item.aspect_frame.set_child(list_item.picture)

        list_item.download_button = Gtk.Button(icon_name="folder-download-symbolic", tooltip_text="Download Wallpaper")
        list_item.download_button.add_css_class("circular")
        list_item.download_button.add_css_class("drop-shadow")
        list_item.download_button.set_halign(Gtk.Align.END)
        list_item.download_button.set_valign(Gtk.Align.START)
        list_item.download_button.set_margin_top(6)
        list_item.download_button.set_margin_end(6)

        list_item.resolution_label = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.END)
        list_item.resolution_label.set_margin_top(6)
        list_item.resolution_label.set_margin_bottom(6)
        list_item.resolution_label.set_margin_start(6)
        list_item.resolution_label.set_margin_end(6)
        list_item.resolution_label.add_css_class("resolution-label")

        picture_overlay = Gtk.Overlay()
        picture_overlay.set_child(list_item.aspect_frame)
        picture_overlay.add_overlay(list_item.download_button)
        picture_overlay.add_overlay(list_item.resolution_label)

        label = Gtk.Label(wrap=True, max_width_chars=20, ellipsize=Pango.EllipsizeMode.END, halign=Gtk.Align.CENTER)
        
        list_item.label_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=250)
        list_item.label_revealer.set_child(label)

        item_box.append(picture_overlay)
        item_box.append(list_item.label_revealer)
        
        revealer.set_child(item_box)
        list_item.set_child(revealer)
        
        left_click_controller = Gtk.GestureClick.new()
        left_click_controller.set_button(Gdk.BUTTON_PRIMARY)
        left_click_controller.connect("pressed", app._on_list_item_activated, list_item)
        revealer.add_controller(left_click_controller)

        right_click_controller = Gtk.GestureClick.new()
        right_click_controller.set_button(Gdk.BUTTON_SECONDARY)
        right_click_controller.connect("pressed", app._on_online_list_item_right_clicked, list_item)
        revealer.add_controller(right_click_controller)

    def on_bind(factory, list_item):
        item = list_item.get_item()
        if not isinstance(item, OnlineWallpaperItem): return

        list_item.resolution_label.set_text(item.resolution or "")

        local_path = app._get_online_wallpaper_local_path(item)
        item.is_downloaded = bool(local_path)
        item.local_path = str(local_path) if local_path else None

        def on_size_changed(item_obj):
            width = app.preview_size
            height = int(width * app.aspect_ratio)
            ratio = 1.0 / app.aspect_ratio if app.aspect_ratio else 16/9
            list_item.aspect_frame.set_ratio(ratio)
            list_item.aspect_frame.set_size_request(width, height)
            list_item.label_revealer.set_reveal_child(app.show_labels)
            list_item.get_child().get_child().set_spacing(4 if app.show_labels else 0)
        
        list_item.handler_id = item.connect('preview-size-changed', on_size_changed)
        on_size_changed(item)

        list_item.label_revealer.get_child().set_text(item.title or item.wall_id)

        app._load_online_thumbnail(item, list_item.picture)

        def update_download_button_ui(item_obj, is_downloaded, local_path):
            if is_downloaded:
                list_item.download_button.set_icon_name("emblem-ok-symbolic")
                list_item.download_button.set_tooltip_text("Apply Wallpaper")
                if hasattr(list_item.download_button, 'handler_id') and list_item.download_button.handler_id > 0:
                    list_item.download_button.disconnect(list_item.download_button.handler_id)
                list_item.download_button.handler_id = list_item.download_button.connect("clicked", app._on_apply_downloaded_wallpaper_clicked, item)
            else:
                list_item.download_button.set_icon_name("folder-download-symbolic")
                list_item.download_button.set_tooltip_text("Download Wallpaper")
                if hasattr(list_item.download_button, 'handler_id') and list_item.download_button.handler_id > 0:
                    list_item.download_button.disconnect(list_item.download_button.handler_id)
                list_item.download_button.handler_id = list_item.download_button.connect("clicked", app._on_download_wallpaper_clicked, item)
            list_item.download_button.set_sensitive(True)

        update_download_button_ui(item, item.is_downloaded, item.local_path)

        if hasattr(list_item, 'download_status_handler_id') and list_item.download_status_handler_id > 0:
            item.disconnect(list_item.download_status_handler_id)
        list_item.download_status_handler_id = item.connect('download-status-changed', update_download_button_ui)
        
        list_item.get_child().set_reveal_child(False)
        GLib.timeout_add(list_item.get_position() * 40, lambda: (list_item.get_child().set_reveal_child(True), GLib.SOURCE_REMOVE)[1])

    def on_unbind(factory, list_item):
        if hasattr(list_item, 'handler_id') and list_item.get_item():
            list_item.get_item().disconnect(list_item.handler_id)

    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    factory.connect("unbind", on_unbind)
    return factory

def create_wallpaper_item_factory(app):
    """Creates a factory for items in the GridView (Static/Live)."""
    factory = Gtk.SignalListItemFactory()

    def on_setup(factory, list_item):
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=300)
        item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        list_item.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        list_item.aspect_frame = Gtk.AspectFrame(xalign=0.5, yalign=0.5, obey_child=False)
        list_item.aspect_frame.set_child(list_item.picture)
        
        label = Gtk.Label(wrap=True, max_width_chars=20, ellipsize=Pango.EllipsizeMode.END, halign=Gtk.Align.CENTER)
        
        list_item.label_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=250)
        list_item.label_revealer.set_child(label)

        item_box.append(list_item.aspect_frame)
        item_box.append(list_item.label_revealer)
        
        revealer.set_child(item_box)
        list_item.set_child(revealer)
        
        click_controller = Gtk.GestureClick.new()
        click_controller.set_button(Gdk.BUTTON_PRIMARY)
        click_controller.connect("pressed", app._on_list_item_activated, list_item)
        revealer.add_controller(click_controller)

        right_click_controller = Gtk.GestureClick.new()
        right_click_controller.set_button(Gdk.BUTTON_SECONDARY)
        right_click_controller.connect("pressed", app._on_list_item_right_clicked, list_item)
        revealer.add_controller(right_click_controller)

    def on_bind(factory, list_item):
        item = list_item.get_item()
        if not isinstance(item, WallpaperItem): return

        def on_size_changed(item_obj):
            width = app.preview_size
            height = int(width * app.aspect_ratio)
            ratio = 1.0 / app.aspect_ratio if app.aspect_ratio else 16/9
            list_item.aspect_frame.set_ratio(ratio)
            list_item.aspect_frame.set_size_request(width, height)
            list_item.label_revealer.set_reveal_child(app.show_labels)
            list_item.get_child().get_child().set_spacing(4 if app.show_labels else 0)
        
        list_item.handler_id = item.connect('preview-size-changed', on_size_changed)
        on_size_changed(item)

        is_url = isinstance(item.path, str)
        name = item.title or (item.path if is_url else item.path.name)
        list_item.label_revealer.get_child().set_text(name)

        thumb_path = app._get_thumbnail_path_or_trigger_generation(item)
        if thumb_path:
            if thumb_path not in app.texture_cache:
                try:
                    texture = Gdk.Texture.new_from_filename(thumb_path)
                    app.texture_cache[thumb_path] = texture
                except GLib.Error as e:
                    print(f"Error loading texture {thumb_path}: {e}")
            
            if thumb_path in app.texture_cache:
                list_item.picture.set_paintable(app.texture_cache[thumb_path])
        
        list_item.get_child().set_reveal_child(False)
        GLib.timeout_add(list_item.get_position() * 40, lambda: (list_item.get_child().set_reveal_child(True), GLib.SOURCE_REMOVE)[1])

    def on_unbind(factory, list_item):
        if hasattr(list_item, 'handler_id') and list_item.get_item():
            list_item.get_item().disconnect(list_item.handler_id)

    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    factory.connect("unbind", on_unbind)
    return factory
