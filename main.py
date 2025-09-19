import gi
import subprocess
from pathlib import Path
import threading
import random
import sys
import re
import math
import datetime
import json

# Required GTK and Adwaita versions
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango, GdkPixbuf, GObject

# --- Configuration ---
SUPPORTED_STATIC = ['.png', '.jpeg', '.jpg', '.bmp']
SUPPORTED_LIVE = ['.gif', '.mp4', '.mov', '.mkv']
BACKEND_PROCESSES = {
    'swaybg': 'swaybg',
    'swww': 'swww-daemon',
    'hyprpaper': 'hyprpaper',
    'mpvpaper': 'mpvpaper'
}

# --- GObject Helper for Recode Queue ---
class RecodeQueueItem(GObject.Object):
    """A GObject for items in the recode queue popover."""
    text = GObject.Property(type=str)
    status = GObject.Property(type=str)
    wallpaper_item = GObject.Property(type=object)

    def __init__(self, text, status, wallpaper_item):
        super().__init__()
        self.text = text
        self.status = status
        self.wallpaper_item = wallpaper_item

# --- Wallpaper Item ---
class WallpaperItem(GObject.Object):
    """A GObject representing a single wallpaper file."""
    __gsignals__ = {
        'preview-size-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }
    path = GObject.Property(type=object)

    def __init__(self, path):
        super().__init__()
        self.path = path

# --- Utility Functions ---
def is_backend_installed(backend):
    """Checks if a backend command is available in the system's PATH."""
    try:
        subprocess.run(['which', backend], check=True, capture_output=True, text=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def get_monitor_refresh_rate():
    """Gets the refresh rate of the primary monitor."""
    try:
        result = subprocess.run(['hyprctl', 'monitors'], capture_output=True, text=True, check=True)
        match = re.search(r'@(\d+)\.\d+', result.stdout)
        if match:
            return int(match.group(1))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    
    try:
        result = subprocess.run(['wlr-randr'], capture_output=True, text=True, check=True)
        match = re.search(r'@\s*(\d+)\.\d+\s*Hz', result.stdout)
        if match:
            return int(match.group(1))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return 60 # Default fallback

def get_monitor_resolution(window=None):
    """Gets the resolution (width, height) of the monitor the window is on."""
    if window:
        try:
            display = window.get_display()
            monitor = display.get_monitor_at_surface(window.get_surface())
            if monitor:
                rect = monitor.get_geometry()
                return rect.width, rect.height
        except Exception as e:
            print(f"GDK method for getting resolution from window failed: {e}. Falling back.")

    try:
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        if monitors and monitors.get_n_items() > 0:
            monitor = monitors.get_item(0)
            if monitor:
                rect = monitor.get_geometry()
                return rect.width, rect.height
    except Exception as e:
        print(f"GDK monitor enumeration failed: {e}. Falling back to command-line.")

    try:
        result = subprocess.run(['hyprctl', 'monitors'], capture_output=True, text=True, check=True)
        match = re.search(r'Monitor .*\n\s*size: (\d+)x(\d+)', result.stdout)
        if match:
            return int(match.group(1)), int(match.group(2))
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            result = subprocess.run(['wlr-randr'], capture_output=True, text=True, check=True)
            match = re.search(r'(\d+)x(\d+)', result.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None, None
    return None, None

def get_monitor_aspect_ratio(window=None):
    """Gets the aspect ratio of the monitor."""
    width, height = get_monitor_resolution(window)
    if width and height:
        return height / width
    return 9 / 16

def kill_backend_processes():
    """Kills running wallpaper backend processes."""
    for name, proc_name in BACKEND_PROCESSES.items():
        if name in ['swww']: # swww has its own daemon management
            continue
        subprocess.run(['pkill', '-f', proc_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def build_command(backend, path, app_settings):
    """Builds the command to set a wallpaper with a given backend."""
    if backend == 'swaybg':
        return f'swaybg -i "{path}"'
    if backend == 'swww':
        transition_type = app_settings.get_string('swww-transition-type')
        duration = app_settings.get_int('swww-transition-duration')
        fill_type = app_settings.get_string('swww-fill-type').lower()
        fps = app_settings.get_int('swww-transition-fps')
        return f'swww img --resize {fill_type} --transition-type {transition_type} --transition-fps {fps} --transition-duration {duration} "{path}"'
    if backend == 'hyprpaper':
        return f'hyprpaper --output * --set "{path}"'
    if backend == 'mpvpaper':
        socket_path = app_settings.get_string('mpv-socket-path')
        volume = app_settings.get_int('video-volume')
        sound_enabled = app_settings.get_boolean('enable-video-sound')
        audio_opts = f"loop volume={volume}" if sound_enabled else "loop volume=0"
        if not socket_path:
            return None
        return f'mpvpaper -vs -o "{audio_opts} input-ipc-server={socket_path}" ALL "{path}"'
    return None

# --- Preferences Window ---
class PreferencesWindow:
    """Builds the preferences view for the application."""
    def __init__(self, app):
        self.app = app
        self.settings = app.settings
        self.volume_label = None
        self.entry_custom_css_path = None

    def _setup_slider_scroll_controller(self, slider):
        """Adds a scroll controller to a slider to allow changing value with the mouse wheel."""
        controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        
        def on_scroll(controller, dx, dy):
            adjustment = slider.get_adjustment()
            step = 2
            current_value = adjustment.get_value()
            new_value = current_value - (dy * step)
            new_value = max(adjustment.get_lower(), min(new_value, adjustment.get_upper()))
            adjustment.set_value(new_value)
            return True

        controller.connect("scroll", on_scroll)
        slider.add_controller(controller)

    def create_preferences_view(self):
        """Creates and returns the Adw.PreferencesPage widget."""
        preferences_page = Adw.PreferencesPage()

        general_group = Adw.PreferencesGroup(title="General")
        preferences_page.add(general_group)

        row_dir = Adw.ActionRow(title='Wallpaper Directory')
        btn_dir = Gtk.Button(label='Change…', margin_top=8, margin_bottom=8)
        btn_dir.connect('clicked', self.app._prompt_directory)
        row_dir.add_suffix(btn_dir)
        row_dir.set_activatable_widget(btn_dir)
        general_group.add(row_dir)

        row_clear_cache = Adw.ActionRow(title="Clear Thumbnail Cache")
        clear_button = Gtk.Button(label="Clear", margin_top=8, margin_bottom=8)
        clear_button.connect('clicked', self.app._on_clear_cache_clicked)
        clear_button.add_css_class("destructive-action")
        row_clear_cache.add_suffix(clear_button)
        row_clear_cache.set_activatable_widget(clear_button)
        general_group.add(row_clear_cache)

        all_static_backends = ['swaybg', 'swww', 'hyprpaper']
        installed_static_backends = [b for b in all_static_backends if is_backend_installed(b)]

        video_group = None
        if is_backend_installed('mpvpaper'):
            video_group = Adw.PreferencesGroup(title="mpvpaper Settings", description="Option for the mpvpaper backend")
            
            row_enable_sound = Adw.SwitchRow(title="Enable Sound", active=self.app.enable_video_sound)
            row_enable_sound.connect('notify::active', self.app._on_enable_sound_toggled)
            video_group.add(row_enable_sound)

            row_volume = Adw.ActionRow(title="Video Volume")
            volume_adjustment = Gtk.Adjustment(value=self.app.video_volume, lower=0, upper=150, step_increment=1)
            volume_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=volume_adjustment, digits=0, hexpand=True)
            self._setup_slider_scroll_controller(volume_scale)
            volume_adjustment.connect('value-changed', self.app._on_video_volume_changed)
            
            self.volume_label = Gtk.Label(label=f"{int(self.app.video_volume)}%", width_chars=4, xalign=1)
            
            volume_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            volume_box.append(volume_scale)
            volume_box.append(self.volume_label)

            row_volume.add_suffix(volume_box)
            row_volume.set_activatable_widget(volume_scale)
            video_group.add(row_volume)
            row_enable_sound.bind_property("active", row_volume, "sensitive", Gio.SettingsBindFlags.DEFAULT)

            row_hide_original = Adw.SwitchRow(title="Hide original file after recoding", active=self.app.hide_original_after_recode)
            row_hide_original.connect('notify::active', self.app._on_hide_original_toggled)
            video_group.add(row_hide_original)

            row_recode_all = Adw.ActionRow(title="Recode all High-Res videos")
            btn_recode_all = Gtk.Button(label="Recode All", margin_top=8, margin_bottom=8)
            btn_recode_all.connect('clicked', self.app._on_recode_all_clicked)
            row_recode_all.add_suffix(btn_recode_all)
            row_recode_all.set_activatable_widget(btn_recode_all)
            video_group.add(row_recode_all)

        swww_group = None
        if is_backend_installed('swww'):
            swww_group = Adw.PreferencesGroup(title="swww Settings", description="Options for the swww backend")
            
            transition_types = ["any", "simple", "fade", "left", "right", "top", "bottom", "wipe", "wave", "grow", "outer"]
            row_transition_type = Adw.ComboRow(title="Transition Type", subtitle="Sets the type of transition.", model=Gtk.StringList.new(transition_types))
            current_transition = self.settings.get_string('swww-transition-type')
            try:
                row_transition_type.set_selected(transition_types.index(current_transition))
            except ValueError:
                row_transition_type.set_selected(0)
            row_transition_type.connect('notify::selected', self.app._on_swww_transition_type_changed)
            swww_group.add(row_transition_type)

            row_fps = Adw.ActionRow(title="Transition FPS", subtitle="Frame rate for the transition effect.")
            fps_adjustment = Gtk.Adjustment(value=self.app.swww_transition_fps, lower=1, upper=240, step_increment=1)
            fps_spin = Gtk.SpinButton(adjustment=fps_adjustment, digits=0, margin_top=8, margin_bottom=8)
            fps_adjustment.connect('value-changed', self.app._on_swww_fps_changed)
            row_fps.add_suffix(fps_spin)
            row_fps.set_activatable_widget(fps_spin)
            swww_group.add(row_fps)

            row_duration = Adw.ActionRow(title="Transition Duration", subtitle="How long the transition takes to complete in seconds")
            duration_adjustment = Gtk.Adjustment(value=self.app.swww_transition_duration, lower=0, upper=10, step_increment=1)
            duration_spin = Gtk.SpinButton(adjustment=duration_adjustment, digits=0, margin_top=8, margin_bottom=8)
            duration_adjustment.connect('value-changed', self.app._on_swww_duration_changed)
            row_duration.add_suffix(duration_spin)
            row_duration.set_activatable_widget(duration_spin)
            swww_group.add(row_duration)

            fill_types = ["Fit", "Stretch", "Crop"]
            row_fill_type = Adw.ComboRow(title="Fill Type", subtitle="Whether to resize the image and the method by which to resize it", model=Gtk.StringList.new(fill_types))
            current_fill = self.settings.get_string('swww-fill-type')
            try:
                row_fill_type.set_selected(fill_types.index(current_fill))
            except ValueError:
                row_fill_type.set_selected(0)
            row_fill_type.connect('notify::selected', self.app._on_swww_fill_type_changed)
            swww_group.add(row_fill_type)

        def update_backend_settings_visibility(*args):
            static_backend = self.settings.get_string('static-backend')
            live_backend = self.settings.get_string('live-backend')
            if video_group:
                video_group.set_visible(live_backend == 'mpvpaper')
            if swww_group:
                swww_group.set_visible(static_backend == 'swww' or live_backend == 'swww')

        if not installed_static_backends:
            row_static = Adw.ActionRow(title='Static Wallpaper Backend', subtitle='No supported backends found.')
        else:
            row_static = Adw.ComboRow(title='Static Wallpaper Backend', model=Gtk.StringList.new(installed_static_backends))
            current_static_backend = self.settings.get_string('static-backend')
            try:
                row_static.set_selected(installed_static_backends.index(current_static_backend))
            except ValueError:
                if installed_static_backends:
                    row_static.set_selected(0)
            
            def on_static_backend_changed(combo, _):
                backend = installed_static_backends[combo.get_selected()]
                self.settings.set_string('static-backend', backend)
                update_backend_settings_visibility()
            row_static.connect('notify::selected', on_static_backend_changed)
        general_group.add(row_static)

        all_live_backends = ['swww', 'mpvpaper']
        installed_live_backends = [b for b in all_live_backends if is_backend_installed(b)]

        if not installed_live_backends:
            row_live = Adw.ActionRow(title='Live Wallpaper Backend', subtitle='No supported backends found.')
        else:
            row_live = Adw.ComboRow(title='Live Wallpaper Backend', model=Gtk.StringList.new(installed_live_backends))
            current_live_backend = self.settings.get_string('live-backend')
            try:
                selected_index = installed_live_backends.index(current_live_backend)
                row_live.set_selected(selected_index)
            except ValueError:
                if installed_live_backends:
                    row_live.set_selected(0)

            def on_live_backend_changed(combo, _):
                backend = installed_live_backends[combo.get_selected()]
                self.settings.set_string('live-backend', backend)
                self.app.live_filter.changed(Gtk.FilterChange.DIFFERENT)
                update_backend_settings_visibility()
            row_live.connect('notify::selected', on_live_backend_changed)
        general_group.add(row_live)

        if video_group:
            preferences_page.add(video_group)
        if swww_group:
            preferences_page.add(swww_group)
        
        update_backend_settings_visibility()

        appearance_group = Adw.PreferencesGroup(title="Appearance")
        preferences_page.add(appearance_group)

        row_preview = Adw.ActionRow(title='Preview Size')
        self.app.preview_adjustment = Gtk.Adjustment(value=self.app.preview_size, lower=64, upper=512, step_increment=self.app.scroll_step)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.app.preview_adjustment, digits=0, hexpand=True)
        self._setup_slider_scroll_controller(scale)
        self.app.preview_adjustment.connect('value-changed', self.app._on_preview_adjustment_changed)
        row_preview.add_suffix(scale)
        row_preview.set_activatable_widget(scale)
        appearance_group.add(row_preview)

        row_scroll_step = Adw.ActionRow(title="Zoom Scroll Step")
        scroll_step_adjustment = Gtk.Adjustment(value=self.app.scroll_step, lower=1, upper=64, step_increment=1)
        scroll_step_adjustment.connect('value-changed', self.app._on_scroll_step_changed)
        spin_button = Gtk.SpinButton(adjustment=scroll_step_adjustment, climb_rate=1, digits=0, margin_top=8, margin_bottom=8)
        row_scroll_step.add_suffix(spin_button)
        row_scroll_step.set_activatable_widget(spin_button)
        appearance_group.add(row_scroll_step)

        self.show_labels_switch = Adw.SwitchRow(title="Show Item Labels", active=self.app.show_labels)
        self.show_labels_switch.connect('notify::active', self.app._on_show_labels_toggled)
        appearance_group.add(self.show_labels_switch)
        
        row_corner_radius = Adw.ActionRow(title="Corner Radius")
        corner_radius_adjustment = Gtk.Adjustment(value=self.app.corner_radius, lower=0, upper=64, step_increment=1)
        corner_radius_adjustment.connect('value-changed', self.app._on_corner_radius_changed)
        corner_radius_spin_button = Gtk.SpinButton(adjustment=corner_radius_adjustment, climb_rate=1, digits=0, margin_top=8, margin_bottom=8)
        row_corner_radius.add_suffix(corner_radius_spin_button)
        row_corner_radius.set_activatable_widget(corner_radius_spin_button)
        appearance_group.add(row_corner_radius)

        # --- Custom CSS Expander Row ---
        expander_row = Adw.ExpanderRow(title="Use Custom CSS")
        expander_row.set_expanded(self.app.use_custom_css)
        
        # Add a switch to the expander row for better visualization
        css_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        css_switch.set_active(self.app.use_custom_css)
        expander_row.add_suffix(css_switch)
        
        # Connect the switch's toggled signal to the handler
        css_switch.connect('notify::active', self._on_use_custom_css_toggled)
        
        # Bind the switch's state to the expander's expansion
        css_switch.bind_property("active", expander_row, "expanded", Gio.SettingsBindFlags.DEFAULT)

        appearance_group.add(expander_row)

        row_select_custom_css = Adw.ActionRow(title="Custom CSS File Path")
        self.entry_custom_css_path = Gtk.Entry(hexpand=True, text=self.app.custom_css_path or "", margin_top=8, margin_bottom=8)
        self.entry_custom_css_path.connect("changed", self._on_custom_css_path_changed)
        
        file_chooser_button = Gtk.Button(label="Browse...", margin_top=8, margin_bottom=8)
        file_chooser_button.connect('clicked', self._on_select_css_file_clicked)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(self.entry_custom_css_path)
        box.append(file_chooser_button)
        
        row_select_custom_css.add_suffix(box)
        row_select_custom_css.set_activatable_widget(self.entry_custom_css_path)
        expander_row.add_row(row_select_custom_css)

        row_reload_css = Adw.ActionRow(title="Reload Custom CSS")
        btn_reload_css = Gtk.Button(label="Reload", margin_top=8, margin_bottom=8)
        btn_reload_css.connect('clicked', self.app._on_reload_css_clicked)
        row_reload_css.add_suffix(btn_reload_css)
        row_reload_css.set_activatable_widget(btn_reload_css)
        expander_row.add_row(row_reload_css)

        return preferences_page

    def _on_use_custom_css_toggled(self, switch, _):
        self.app.use_custom_css = switch.get_active()
        self.settings.set_boolean('use-custom-css', self.app.use_custom_css)
        self.app._update_css()

    def _on_custom_css_path_changed(self, entry):
        self.app.custom_css_path = entry.get_text()
        self.settings.set_string('custom-css-path', self.app.custom_css_path)
        self.app._update_css()
        
    def _on_select_css_file_clicked(self, button):
        """Opens a file chooser dialog to select a CSS file."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Select a Custom CSS File")
        
        # Create a filter for CSS files
        css_filter = Gtk.FileFilter()
        css_filter.set_name("CSS files")
        css_filter.add_mime_type("text/css")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(css_filter)
        dialog.set_filters(filters)

        dialog.open(self.app.window, None, self._on_select_css_file_finish)

    def _on_select_css_file_finish(self, source, result):
        """Callback for when the CSS file has been selected."""
        try:
            file = source.open_finish(result)
            if file:
                self.entry_custom_css_path.set_text(file.get_path())
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print(f"Error selecting file: {e.message}")


# --- Main Application Class ---
class Manpaper(Adw.Application):
    """The main application class for Manpaper."""
    def __init__(self):
        super().__init__(application_id='io.hxprlee.Manpaper', flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect('shutdown', self._on_shutdown)
        Adw.init()
        self.settings = Gio.Settings.new('io.hxprlee.Manpaper')
        self.window = None
        self.toast_overlay = None
        self.search_text = ""
        self.right_clicked_item = None
        self.mpv_process = None

        self.static_store = Gio.ListStore.new(WallpaperItem)
        self.static_filter = Gtk.CustomFilter.new(self._wallpaper_filter_func)
        self.static_model = Gtk.SingleSelection.new(Gtk.FilterListModel.new(self.static_store, self.static_filter))
        
        self.live_store = Gio.ListStore.new(WallpaperItem)
        self.live_filter = Gtk.CustomFilter.new(self._live_wallpaper_filter_func)
        self.live_model = Gtk.SingleSelection.new(Gtk.FilterListModel.new(self.live_store, self.live_filter))

        self.static_view = None
        self.live_view = None
        self.view_stack = None
        self.random_button = None
        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, spinning=False, visible=False)
        
        self.recode_queue = []
        self.recode_currently_running = None
        self.recode_lock = threading.Lock()
        self.recode_process = None
        self.recode_popover_store = Gio.ListStore.new(RecodeQueueItem)

        # --- Threading and Caching Attributes ---
        self.thumbnail_lock = threading.Lock()
        self.thumbnails_in_progress = set()
        self.background_tasks = 0
        
        self.preview_size = self.settings.get_int('preview-size')
        self.scroll_step = self.settings.get_int('scroll-step')
        self.show_labels = self.settings.get_boolean('show-labels')
        self.corner_radius = self.settings.get_int('corner-radius')
        self.custom_css_path = self.settings.get_string('custom-css-path')
        self.use_custom_css = self.settings.get_boolean('use-custom-css')
        self.hide_original_after_recode = self.settings.get_boolean('hide-original-after-recode')
        self.enable_video_sound = self.settings.get_boolean('enable-video-sound')
        self.video_volume = self.settings.get_int('video-volume')
        self.mpv_socket_path = self.settings.get_string('mpv-socket-path')
        self.swww_transition_type = self.settings.get_string('swww-transition-type')
        self.swww_transition_duration = self.settings.get_int('swww-transition-duration')
        self.swww_fill_type = self.settings.get_string('swww-fill-type')
        self.swww_transition_fps = self.settings.get_int('swww-transition-fps')
        if self.swww_transition_fps == 0: # Sentinel for first run
            self.swww_transition_fps = get_monitor_refresh_rate()
            self.settings.set_int('swww-transition-fps', self.swww_transition_fps)

        
        self.aspect_ratio = get_monitor_aspect_ratio()
        self.preview_adjustment = None
        self.texture_cache = {}
        self.cache_dir = Path(GLib.get_user_cache_dir()) / 'manpaper' / 'thumbnails'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.css_provider = Gtk.CssProvider()
        self.corner_radius_css_provider = Gtk.CssProvider()
        self.custom_css_provider = Gtk.CssProvider()
        self._update_css()
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.StyleContext.add_provider_for_display(display, self.corner_radius_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._update_corner_radius_css()
        
        self.search_button = None
        self.search_button_revealer = None
        self.search_entry = None
        self.title_stack = None
        self.bottom_bar_container = None
        self.fade_revealer = None
        self.slide_revealer = None
        self.menu_popover = None
        self.header_revealer = None
        self.recode_button = None
        self.recode_spinner = None
        self.recode_revealer_container = None

        self.zen_mode_active = False
        self.original_show_labels = self.show_labels

        self.prefs_window = PreferencesWindow(self)

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def do_activate(self):
        if not self.window:
            self.window = self._create_window()

        self._check_and_set_default_backends()
        self.view_stack.connect('notify::visible-child-name', self._on_view_changed)
        self._load_wallpapers_async()
        self._setup_actions()
        self._setup_key_controller()

        self.window.present()

    def _on_shutdown(self, app):
        """Clean up resources on application exit."""
        # The mpvpaper process is no longer terminated here to allow it to persist.
        pass

    def send_mpv_command(self, command):
        """Sends a JSON IPC command to the mpv socket using socat."""
        if not self.mpv_socket_path:
            return
        
        if not is_backend_installed('socat'):
            if self.toast_overlay:
                GLib.idle_add(self.toast_overlay.add_toast, Adw.Toast.new("socat is not installed. IPC commands cannot be sent."))
            return

        try:
            socket_file = Path(self.mpv_socket_path).expanduser()
            if not socket_file.is_socket():
                return

            command_str = json.dumps({"command": command})
            subprocess.Popen(f"echo '{command_str}' | socat - '{socket_file}'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Failed to send command to mpv socket: {e}")

    def _create_window(self):
        """Creates the main application window and its widgets."""
        win = Adw.ApplicationWindow(application=self, title='Manpaper', default_width=800, default_height=600)
        win.set_size_request(628, 400)
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
        self.search_entry.connect("search-changed", self._on_search_changed)

        view_switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.title_stack.add_named(view_switcher, "switcher")
        self.title_stack.add_named(self.search_entry, "search")

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Search")
        self.search_button.connect("toggled", self._on_search_toggled)
        
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
        
        popover_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_vbox.set_size_request(350, -1)
        recode_popover.set_child(popover_vbox)

        popover_list_view = Gtk.ListView.new(Gtk.SingleSelection.new(self.recode_popover_store), self._recode_popover_factory())
        popover_list_view.add_css_class("recode-popover-list")
        scrolled_list = Gtk.ScrolledWindow(child=popover_list_view, max_content_height=400, hscrollbar_policy=Gtk.PolicyType.NEVER)
        popover_vbox.append(scrolled_list)

        stop_all_button = Gtk.Button(label="Stop All", margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        stop_all_button.add_css_class("destructive-action")
        stop_all_button.connect('clicked', self._on_stop_all_recodes_clicked)
        popover_vbox.append(stop_all_button)
        
        header.pack_end(self.recode_revealer_container)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        self.menu_popover = Gtk.PopoverMenu()
        menu_button.set_popover(self.menu_popover)
        header.pack_end(menu_button)

        self.static_view = self._create_grid_view(self.static_model)
        static_page = self.view_stack.add_titled(self._create_scrolled_window(self.static_view), 'static', 'Static')
        static_page.set_icon_name('image-x-generic-symbolic')

        self.live_view = self._create_grid_view(self.live_model)
        live_page = self.view_stack.add_titled(self._create_scrolled_window(self.live_view), 'live', 'Live')
        live_page.set_icon_name('video-x-generic-symbolic')
        
        prefs_view = self.prefs_window.create_preferences_view()
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
        self.random_button.connect('clicked', self._on_random_button_clicked)
        button_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_content.append(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        button_content.append(Gtk.Label(label="Random"))
        self.random_button.set_child(button_content)
        self.random_button.add_css_class("pill")
        self.random_button.add_css_class("suggested-action")
        
        random_button_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=500, reveal_child=True, halign=Gtk.Align.END, valign=Gtk.Align.END, margin_bottom=24, margin_end=24)
        random_button_revealer.set_child(self.random_button)
        random_button_revealer.add_css_class("pill-revealer")

        self.status_page = Adw.StatusPage(icon_name="system-search-symbolic", title="No Results Found", description="Try a different search.", visible=False)

        overlay = Gtk.Overlay(vexpand=True)
        overlay.set_child(self.view_stack)
        overlay.add_overlay(self.spinner)
        overlay.add_overlay(self.status_page)
        overlay.add_overlay(random_button_revealer)
        content.set_content(overlay)
        
        self.toast_overlay = Adw.ToastOverlay(child=content)
        win.set_content(self.toast_overlay)
        return win

    def _recode_popover_factory(self):
        """Creates a factory for items in the Recode popover ListView."""
        factory = Gtk.SignalListItemFactory()

        def setup_cb(f, list_item):
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)
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
            stop_button.handler_id = stop_button.connect("clicked", self._on_stop_one_recode_clicked, queue_item.wallpaper_item)

        factory.connect("setup", setup_cb)
        factory.connect("bind", bind_cb)
        return factory

    def _create_grid_view(self, model):
        """Helper to create a Gtk.GridView."""
        view = Gtk.GridView.new(model, self._item_factory())
        view.connect('activate', self._on_wallpaper_activated)
        return view

    def _create_scrolled_window(self, child):
        """Helper to create a Gtk.ScrolledWindow for a grid view."""
        scrolled = Gtk.ScrolledWindow(margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        scrolled.set_child(child)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect("scroll", self._on_scroll_resize)
        scrolled.add_controller(scroll_controller)
        return scrolled

    def _setup_actions(self):
        """Sets up application actions and menu."""
        menu_model = Gio.Menu()
        menu_model.append("Zen Mode", "app.zen_mode")
        menu_model.append("Keyboard Shortcuts", "app.shortcuts")
        menu_model.append("About", "app.about")
        self.menu_popover.set_menu_model(menu_model)

        action_zen = Gio.SimpleAction(name="zen_mode")
        action_zen.connect("activate", self._on_zen_mode_toggled)
        self.add_action(action_zen)

        action_shortcuts = Gio.SimpleAction(name="shortcuts")
        action_shortcuts.connect("activate", self._on_shortcuts_clicked)
        self.add_action(action_shortcuts)

        action_about = Gio.SimpleAction(name="about")
        action_about.connect("activate", self._on_about_clicked)
        self.add_action(action_about)

        action_delete = Gio.SimpleAction(name="delete_wallpaper")
        action_delete.connect("activate", self._on_delete_wallpaper_activated)
        self.add_action(action_delete)

        action_properties = Gio.SimpleAction(name="show_properties")
        action_properties.connect("activate", self._on_show_properties_activated)
        self.add_action(action_properties)

        action_recode = Gio.SimpleAction(name="recode_video")
        action_recode.connect("activate", self._on_recode_video_activated)
        self.add_action(action_recode)

    def _setup_key_controller(self):
        """Sets up the main key controller for shortcuts."""
        key_controller = Gtk.EventControllerKey.new()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.window.add_controller(key_controller)

    def _check_and_set_default_backends(self):
        """Checks if configured backends are installed, sets a default, and notifies the user if changed."""
        all_static = ['swaybg', 'swww', 'hyprpaper']
        installed_static = [b for b in all_static if is_backend_installed(b)]
        current_static = self.settings.get_string('static-backend')

        if installed_static and current_static not in installed_static:
            new_default = installed_static[0]
            self.toast_overlay.add_toast(Adw.Toast.new(f"Static backend '{current_static}' not found. Defaulting to '{new_default}'."))
            self.settings.set_string('static-backend', new_default)
        elif not installed_static:
            self.toast_overlay.add_toast(Adw.Toast.new("Warning: No static wallpaper backends found."))

        all_live = ['swww', 'mpvpaper']
        installed_live = [b for b in all_live if is_backend_installed(b)]
        current_live = self.settings.get_string('live-backend')

        if installed_live and current_live not in installed_live:
            new_default = installed_live[0]
            self.toast_overlay.add_toast(Adw.Toast.new(f"Live backend '{current_live}' not found. Defaulting to '{new_default}'."))
            self.settings.set_string('live-backend', new_default)
        elif not installed_live:
            self.toast_overlay.add_toast(Adw.Toast.new("Warning: No live wallpaper backends found."))

    def _update_css(self):
        """Loads default and custom CSS."""
        default_css = '''
            .main-content { box-shadow: inset 0 -4px 8px -4px rgba(0, 0, 0, 0.2); }
            .pill-revealer { box-shadow: 0 0px 12px 8px rgba(0, 0, 0, 0.2); border-radius: 28px; }
            gridview.view { background-color: transparent; }
            .recode-popover-list row { background-color: transparent; }
            .recode-popover-list row:hover { background-color: transparent; }
            .recode-item { background-color: alpha(@theme_fg_color, 0.05); border-radius: 8px; }
        '''
        self.css_provider.load_from_string(default_css)

        display = Gdk.Display.get_default()
        Gtk.StyleContext.remove_provider_for_display(display, self.custom_css_provider)

        if self.use_custom_css and self.custom_css_path and Path(self.custom_css_path).exists():
            try:
                self.custom_css_provider.load_from_path(self.custom_css_path)
                Gtk.StyleContext.add_provider_for_display(display, self.custom_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            except Exception as e:
                self.toast_overlay.add_toast(Adw.Toast.new(f"Error loading custom CSS: {e}"))

    def _update_corner_radius_css(self):
        """Updates the CSS for wallpaper preview corner radius."""
        css = f"picture {{ border-radius: {self.corner_radius}px; }}"
        self.corner_radius_css_provider.load_from_string(css)
        
    def _on_search_toggled(self, button):
        """Handles the toggling of the search button."""
        is_active = button.get_active()
        self.search_button_revealer.set_reveal_child(not is_active)
        self.title_stack.set_visible_child_name("search" if is_active else "switcher")
        self.fade_revealer.set_reveal_child(False)
        GLib.timeout_add(100, lambda: self.fade_revealer.set_reveal_child(True))
        if is_active:
            self.search_entry.grab_focus()
        else:
            self.search_entry.set_text("")
            self.window.set_focus(None)
        self._update_random_button_visibility()

    def _update_random_button_visibility(self):
        """Shows or hides the random button based on context."""
        is_prefs = self.view_stack.get_visible_child_name() == "preferences"
        is_searching = bool(self.search_text)
        if self.random_button:
            self.random_button.get_parent().set_reveal_child(not is_prefs and not is_searching and not self.zen_mode_active)

    def _hide_search_revealer_if_needed(self):
        """Callback to hide the search revealer if still in prefs."""
        if self.view_stack.get_visible_child_name() == "preferences":
            self.search_button_revealer.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _on_view_changed(self, stack, _):
        """Handles view changes in the main stack."""
        self._update_random_button_visibility()
        is_prefs = stack.get_visible_child_name() == "preferences"

        if is_prefs:
            self.search_button_revealer.set_reveal_child(False)
            GLib.timeout_add(300, self._hide_search_revealer_if_needed)
        else:
            self.search_button_revealer.set_visible(True)
            self.search_button_revealer.set_reveal_child(True)

        self.fade_revealer.set_reveal_child(False)
        GLib.timeout_add(100, lambda: (
            self.slide_revealer.set_reveal_child(not is_prefs),
            GLib.timeout_add(50, lambda: (self.fade_revealer.set_reveal_child(True), GLib.SOURCE_REMOVE)[1]),
            GLib.SOURCE_REMOVE
        )[2])

        if is_prefs and self.search_button.get_active():
            self.search_button.set_active(False)

    def _on_zen_mode_toggled(self, *args):
        """Toggles Zen mode, hiding UI elements."""
        if self.menu_popover.is_visible():
            self.menu_popover.popdown()
        self.zen_mode_active = not self.zen_mode_active

        self.header_revealer.set_reveal_child(not self.zen_mode_active)
        self._update_random_button_visibility()

        if self.zen_mode_active:
            self.original_show_labels = self.show_labels
            if self.show_labels:
                self.prefs_window.show_labels_switch.set_active(False)
        elif self.original_show_labels and not self.show_labels:
            self.prefs_window.show_labels_switch.set_active(True)
        self._update_status_page_visibility()

    def _on_shortcuts_clicked(self, *args):
        """Shows the shortcuts window."""
        self.menu_popover.popdown()
        shortcuts_window = Gtk.ShortcutsWindow(transient_for=self.window)
        section = Gtk.ShortcutsSection()
        
        def add_shortcut(group, title, accelerator):
            group.append(Gtk.ShortcutsShortcut(title=title, accelerator=accelerator))

        general_group = Gtk.ShortcutsGroup(title="General")
        add_shortcut(general_group, "Toggle Search Bar", "<Control>F")
        section.append(general_group)

        nav_group = Gtk.ShortcutsGroup(title="Navigation")
        add_shortcut(nav_group, "Go to Static Wallpapers", "<Alt>1")
        add_shortcut(nav_group, "Go to Live Wallpapers", "<Alt>2")
        add_shortcut(nav_group, "Go to Preferences", "<Alt>3")
        section.append(nav_group)

        view_group = Gtk.ShortcutsGroup(title="View")
        add_shortcut(view_group, "Preview Zoom In", "<Ctrl>ScrollUp")
        add_shortcut(view_group, "Preview Zoom Out", "<Ctrl>ScrollDown")
        section.append(view_group)

        shortcuts_window.set_child(section)
        shortcuts_window.present()

    def _on_about_clicked(self, *args):
        """Shows the about dialog."""
        self.menu_popover.popdown()
        dialog = Adw.AboutDialog(
            application_name="Manpaper",
            application_icon="io.hxprlee.Manpaper",
            version="0.1",
            developers=["Gemini", "ChatGPT", "HxprLee"],
            designers=["HxprLee"],
            comments="A simple wallpaper frontend for wlroots-based compositors",
            website="https://github.com/HxprLee/manpaper",
            issue_url="https://github.com/HxprLee/manpaper/issues"
        )
        dialog.present(self.window)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handles global key presses."""
        if keyval == Gdk.KEY_Escape and self.search_button.get_active():
            self.search_button.set_active(False)
            return True
            
        if state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_f:
            if self.view_stack.get_visible_child_name() != 'preferences':
                self.search_button.set_active(not self.search_button.get_active())
                return True
        elif state & Gdk.ModifierType.ALT_MASK:
            key_map = {Gdk.KEY_1: 'static', Gdk.KEY_2: 'live', Gdk.KEY_3: 'preferences'}
            if keyval in key_map:
                self.view_stack.set_visible_child_name(key_map[keyval])
                return True
            elif keyval == Gdk.KEY_z:
                self._on_zen_mode_toggled()
                return True
        return False

    def _item_factory(self):
        """Creates a factory for items in the GridView."""
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        return factory

    def _on_factory_setup(self, factory, list_item):
        """Sets up a new list item widget."""
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=300)
        item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, halign=Gtk.Align.CENTER)
        label = Gtk.Label(wrap=True, max_width_chars=20, ellipsize=Pango.EllipsizeMode.END, halign=Gtk.Align.CENTER)
        
        # Create a revealer for the label
        label_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=250)
        label_revealer.set_child(label)

        item_box.append(picture)
        item_box.append(label_revealer) # Append the revealer instead of the label
        
        revealer.set_child(item_box)
        list_item.set_child(revealer)
        
        # Add single-click activation
        left_click_controller = Gtk.GestureClick.new()
        left_click_controller.set_button(Gdk.BUTTON_PRIMARY)
        left_click_controller.connect("pressed", self._on_list_item_activated, list_item)
        revealer.add_controller(left_click_controller)

        # Add context menu to each item's widget
        right_click_controller = Gtk.GestureClick.new()
        right_click_controller.set_button(Gdk.BUTTON_SECONDARY)
        right_click_controller.connect("pressed", self._on_list_item_right_clicked, list_item)
        revealer.add_controller(right_click_controller)

    def _on_factory_bind(self, factory, list_item):
        """Binds data to a list item widget."""
        revealer = list_item.get_child()
        item_box = revealer.get_child()
        picture = item_box.get_first_child()
        label_revealer = item_box.get_last_child() # This is now the revealer
        label = label_revealer.get_child() # Get the label from the revealer
        item = list_item.get_item()

        if not isinstance(item, WallpaperItem): return

        def on_size_changed(item_obj):
            picture.set_size_request(self.preview_size, int(self.preview_size * self.aspect_ratio))
            label_revealer.set_reveal_child(self.show_labels) # Animate the revealer
            item_box.set_spacing(4 if self.show_labels else 0)
        
        list_item.handler_id = item.connect('preview-size-changed', on_size_changed)
        on_size_changed(item)

        image_path = self._get_thumbnail_path_or_trigger_generation(item)
        if image_path:
            if image_path not in self.texture_cache:
                target_w = self.preview_size
                target_h = int(self.preview_size * self.aspect_ratio)
                self.texture_cache[image_path] = self._create_cropped_texture(image_path, target_w, target_h)
            picture.set_paintable(self.texture_cache.get(image_path))
        else:
            # If path is None, it means thumbnail is being generated. Clear the picture.
            picture.set_paintable(None)

        label.set_text(item.path.stem)
        revealer.set_reveal_child(False)
        GLib.timeout_add(list_item.get_position() * 40, lambda: (revealer.set_reveal_child(True), GLib.SOURCE_REMOVE)[1])

    def _on_factory_unbind(self, factory, list_item):
        """Unbinds data from a list item widget."""
        if hasattr(list_item, 'handler_id') and list_item.get_item():
            list_item.get_item().disconnect(list_item.handler_id)

    def _update_spinner(self):
        """Shows or hides the main spinner based on the background task counter."""
        if self.background_tasks > 0:
            if not self.spinner.get_spinning():
                self.spinner.set_visible(True)
                self.spinner.start()
        else:
            if self.spinner.get_spinning():
                self.spinner.stop()
                self.spinner.set_visible(False)
        return False # for GLib.idle_add

    def _create_cropped_texture(self, path, target_width, target_height):
        """
        Loads a pixbuf from a file and returns a cropped Gdk.Texture that fits
        the target dimensions while preserving the aspect ratio (cover).
        """
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            
            src_width = pixbuf.get_width()
            src_height = pixbuf.get_height()
            if src_width == 0 or src_height == 0: return None

            src_aspect = src_width / src_height
            target_aspect = target_width / target_height

            # Determine scaling factor to cover the target area
            if src_aspect > target_aspect:
                # Source is wider than target, scale to match target height
                scale = target_height / src_height
                scaled_width = int(src_width * scale)
                scaled_height = target_height
            else:
                # Source is taller than (or same aspect as) target, scale to match target width
                scale = target_width / src_width
                scaled_width = target_width
                scaled_height = int(src_height * scale)
            
            # Scale the image
            scaled_pixbuf = pixbuf.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
            
            # Create the final pixbuf with the exact target size
            final_pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, target_width, target_height)
            
            # Determine the source rectangle (from the center of the scaled image)
            src_x = (scaled_width - target_width) // 2
            src_y = (scaled_height - target_height) // 2
            
            # Copy the central part of the scaled image to the final pixbuf
            scaled_pixbuf.copy_area(src_x, src_y, target_width, target_height, final_pixbuf, 0, 0)

            return Gdk.Texture.new_for_pixbuf(final_pixbuf)
        except GLib.Error as e:
            print(f"Error creating cropped texture for {path}: {e}")
            return None

    def _get_thumbnail_path_or_trigger_generation(self, item):
        """
        Gets path for a thumbnail. If it's for a video and doesn't exist,
        it triggers a background generation task.
        """
        if item.path.suffix.lower() in SUPPORTED_STATIC:
            return str(item.path)

        if item.path.suffix.lower() in SUPPORTED_LIVE:
            thumb_path = self.cache_dir / (item.path.stem + '_thumb.jpg')
            
            if thumb_path.exists() and thumb_path.stat().st_mtime >= item.path.stat().st_mtime:
                return str(thumb_path)

            with self.thumbnail_lock:
                if str(item.path) in self.thumbnails_in_progress:
                    return None # Generation already running
                self.thumbnails_in_progress.add(str(item.path))

            self.background_tasks += 1
            GLib.idle_add(self._update_spinner)
            
            thread = threading.Thread(target=self._generate_thumbnail_thread, args=(item, thumb_path), daemon=True)
            thread.start()
            return None
        
        return None

    def _generate_thumbnail_thread(self, item, thumb_path):
        """Runs ffmpegthumbnailer in a background thread."""
        try:
            subprocess.run(
                ['ffmpegthumbnailer', '-i', str(item.path), '-o', str(thumb_path), '-s', '256', '-q', '5'],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            GLib.idle_add(self._on_thumbnail_generated, item)
        except Exception as e:
            print(f"Thumbnail generation failed for {item.path.name}: {e}")
        finally:
            with self.thumbnail_lock:
                if str(item.path) in self.thumbnails_in_progress:
                    self.thumbnails_in_progress.remove(str(item.path))
            self.background_tasks -= 1
            GLib.idle_add(self._update_spinner)

    def _on_thumbnail_generated(self, item):
        """Callback after a thumbnail is created to refresh the specific item."""
        target_path = item.path
        for i in range(self.live_store.get_n_items()):
            current_item = self.live_store.get_item(i)
            if current_item and current_item.path == target_path:
                # Replacing the item is a more robust way to signal a change
                # that requires a re-bind in the view.
                new_item = WallpaperItem(target_path)
                self.live_store.splice(i, 1, [new_item])
                break
        return False

    def _load_wallpapers_async(self):
        """Loads wallpapers in a separate thread."""
        self.background_tasks += 1
        self._update_spinner()
        threading.Thread(target=self._load_wallpapers_sync, daemon=True).start()

    def _load_wallpapers_sync(self):
        """Synchronously loads wallpaper paths from the directory."""
        wallpaper_dir = self.settings.get_string('wallpaper-dir')
        if not wallpaper_dir:
            GLib.idle_add(self._on_wallpapers_loaded, [], [])
            return
        root = Path(wallpaper_dir)
        if not root.is_dir():
            GLib.idle_add(self._on_wallpapers_loaded, [], [])
            return
        static_paths = [p for p in root.rglob('*') if p.suffix.lower() in SUPPORTED_STATIC]
        live_paths = [p for p in root.rglob('*') if p.suffix.lower() in SUPPORTED_LIVE]
        GLib.idle_add(self._on_wallpapers_loaded, static_paths, live_paths)

    def _on_wallpapers_loaded(self, static_paths, live_paths):
        """Updates the stores after wallpapers have been loaded."""
        self.texture_cache.clear()

        # Replace the store contents using splice for a more robust update signal
        static_items = [WallpaperItem(p) for p in static_paths]
        self.static_store.splice(0, self.static_store.get_n_items(), static_items)

        live_items = [WallpaperItem(p) for p in live_paths]
        self.live_store.splice(0, self.live_store.get_n_items(), live_items)

        self.background_tasks -= 1
        self._update_spinner()
        self._update_status_page_visibility()
        return False

    def _on_wallpaper_activated(self, grid, position):
        """Sets the selected wallpaper."""
        item = grid.get_model().get_item(position)
        if item:
            self._set_wallpaper(item)

    def _on_list_item_activated(self, gesture, n_press, x, y, list_item):
        """Handles single-click activation on a wallpaper list item."""
        item = list_item.get_item()
        if item:
            self._set_wallpaper(item)

    def _set_wallpaper(self, item):
        """Sets the system wallpaper using the configured backend."""
        if not isinstance(item, WallpaperItem): return

        path = item.path
        is_static = path.suffix.lower() in SUPPORTED_STATIC
        backend_key = 'static-backend' if is_static else 'live-backend'
        backend = self.settings.get_string(backend_key)

        if not backend:
            backend_type = "static" if is_static else "live"
            self.toast_overlay.add_toast(Adw.Toast.new(f"No {backend_type} backend configured or installed."))
            return

        if backend == 'swww' and not is_static and path.suffix.lower() != '.gif':
            self.toast_overlay.add_toast(Adw.Toast.new("Swww backend only supports .gif for live wallpapers."))
            return
        
        # Always kill existing wallpaper processes before setting a new one
        kill_backend_processes()
        self.mpv_process = None
        
        cmd = build_command(backend, path, self.settings)

        if cmd:
            if backend == 'mpvpaper':
                resolved_socket_path = str(Path(self.mpv_socket_path).expanduser())
                socket_file = Path(resolved_socket_path)
                try:
                    if socket_file.exists(): socket_file.unlink()
                except OSError as e:
                    print(f"Error removing old mpv socket: {e}")
                
                self.mpv_process = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
                
                def monitor_stderr(process):
                    if process.stderr:
                        for line in iter(process.stderr.readline, ''):
                            if line: print(f"[mpvpaper stderr] {line.strip()}")
                        process.stderr.close()
                threading.Thread(target=monitor_stderr, args=(self.mpv_process,), daemon=True).start()
                
                GLib.timeout_add(500, self._set_initial_mpv_state)
            else:
                subprocess.Popen(cmd, shell=True)
            self.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper set to: {path.name}"))

    def _set_initial_mpv_state(self):
        """Sends initial volume and mute commands to a new mpvpaper instance."""
        self.send_mpv_command(["set_property", "volume", self.video_volume])
        self.send_mpv_command(["set_property", "mute", "no" if self.enable_video_sound else "yes"])
        return GLib.SOURCE_REMOVE

    def _on_random_button_clicked(self, button):
        """Sets a random wallpaper from the current view."""
        current_view = self.view_stack.get_visible_child_name()
        model = self.static_model.get_model() if current_view == 'static' else self.live_model.get_model()
        
        if model and model.get_n_items() > 0:
            random_pos = random.randint(0, model.get_n_items() - 1)
            self._set_wallpaper(model.get_item(random_pos))
        else:
            self.toast_overlay.add_toast(Adw.Toast.new("No wallpapers to choose from."))

    def _on_list_item_right_clicked(self, gesture, n_press, x, y, list_item):
        """Handles right-click on a wallpaper list item."""
        item = list_item.get_item()
        if not item: return

        self.right_clicked_item = item
        menu = Gio.Menu()
        if item.path.suffix.lower() in SUPPORTED_LIVE:
            menu.append("Recode to display resolution", "app.recode_video")
        menu.append("Delete", "app.delete_wallpaper")
        menu.append("Properties", "app.show_properties")
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(list_item.get_child())
        popover.popup()

    def _update_recode_ui(self):
        """Updates the spinner and popover based on the recode queue."""
        with self.recode_lock:
            is_active = bool(self.recode_currently_running or self.recode_queue)
            self.recode_revealer_container.set_visible(is_active)
            revealer = self.recode_revealer_container.get_first_child()
            if revealer:
                revealer.set_reveal_child(is_active)
            self.recode_spinner.spinning = is_active
            self.recode_popover_store.remove_all()
            if self.recode_currently_running:
                item = RecodeQueueItem(f"{self.recode_currently_running.path.name}", "Running", self.recode_currently_running)
                self.recode_popover_store.append(item)
            for item_in_queue in self.recode_queue:
                item = RecodeQueueItem(f"{item_in_queue.path.name}", "Queued", item_in_queue)
                self.recode_popover_store.append(item)

    def _on_stop_one_recode_clicked(self, button, item_to_stop):
        """Stops a single recode job from the queue or the running process."""
        with self.recode_lock:
            if self.recode_currently_running == item_to_stop:
                if self.recode_process:
                    try:
                        self.recode_process.terminate()
                        self.toast_overlay.add_toast(Adw.Toast.new(f"Stopping recode for: {item_to_stop.path.name}"))
                    except ProcessLookupError: pass 
                self.recode_currently_running = None
                GLib.idle_add(self._start_next_recode_if_possible)
            elif item_to_stop in self.recode_queue:
                self.recode_queue.remove(item_to_stop)
                self.toast_overlay.add_toast(Adw.Toast.new(f"Removed from queue: {item_to_stop.path.name}"))
        GLib.idle_add(self._update_recode_ui)

    def _on_stop_all_recodes_clicked(self, button):
        """Stops the running recode process and clears the queue."""
        with self.recode_lock:
            self.recode_queue.clear()
            if self.recode_currently_running:
                if self.recode_process:
                    try: self.recode_process.terminate()
                    except ProcessLookupError: pass
                self.recode_currently_running = None
        self.toast_overlay.add_toast(Adw.Toast.new("All recode jobs stopped."))
        self.recode_button.get_popover().popdown()
        GLib.idle_add(self._update_recode_ui)
    
    def _start_next_recode_if_possible(self):
        """Checks the queue and starts the next recode job if the worker is free."""
        with self.recode_lock:
            if self.recode_currently_running or not self.recode_queue: return
            item_to_process = self.recode_queue.pop(0)
            self.recode_currently_running = item_to_process
            GLib.idle_add(self._update_recode_ui)
            thread = threading.Thread(target=self._recode_video_thread, args=(item_to_process, self.window), daemon=True)
            thread.start()

    def _perform_recode(self, item, window):
        """Performs the ffmpeg recoding. Returns (success, error_message)."""
        width, height = get_monitor_resolution(window)
        if not width or not height:
            return False, "Could not determine display resolution."
        
        recoded_dir = item.path.parent / 'recoded'
        recoded_dir.mkdir(parents=True, exist_ok=True)
        
        input_path = str(item.path)
        output_path = str(recoded_dir / f"{item.path.stem}_recoded{item.path.suffix}")
        
        command = ['ffmpeg', '-i', input_path, '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2', '-c:a', 'copy', '-y', output_path]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
            with self.recode_lock: self.recode_process = process
            stdout, stderr = process.communicate()
            return_code = process.wait()
            with self.recode_lock: self.recode_process = None
            if return_code != 0:
                return False, stderr or "Process was terminated or failed."
            return True, None
        except FileNotFoundError:
            return False, "ffmpeg command not found. Is it installed?"
        except Exception as e:
            with self.recode_lock: self.recode_process = None
            return False, str(e)

    def _on_recode_video_activated(self, action, param):
        """Adds a video to the recode queue."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        with self.recode_lock:
            if item in self.recode_queue or self.recode_currently_running == item:
                self.toast_overlay.add_toast(Adw.Toast.new(f"'{item.path.name}' is already in the queue."))
                return
            self.recode_queue.append(item)
        self.toast_overlay.add_toast(Adw.Toast.new(f"Added '{item.path.name}' to the recode queue."))
        self._update_recode_ui()
        self._start_next_recode_if_possible()

    def _recode_video_thread(self, item, window):
        """The actual video recoding logic running in a thread."""
        success, error_message = self._perform_recode(item, window)
        GLib.idle_add(self._on_recode_finished, item, success, error_message)

    def _on_recode_finished(self, item, success, error_message=None):
        """Callback executed on the main thread after an encoding job is done."""
        job_was_cancelled = False
        with self.recode_lock:
            if self.recode_currently_running != item:
                job_was_cancelled = True
            else:
                self.recode_currently_running = None
        if not job_was_cancelled:
            if success:
                toast_message = f"Successfully recoded '{item.path.name}'."
                self.toast_overlay.add_toast(Adw.Toast.new(toast_message))
                GLib.idle_add(self._load_wallpapers_async)
            else:
                if "terminated" not in (error_message or "").lower():
                    toast_message = f"Failed to recode '{item.path.name}'."
                    print(f"recoding failed for {item.path.name}: {error_message}")
                    self.toast_overlay.add_toast(Adw.Toast.new(toast_message))
        self._update_recode_ui()
        self._start_next_recode_if_possible()
        return False

    def _on_delete_wallpaper_activated(self, action, param):
        """Handles the 'Delete' action from the context menu."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        dialog = Adw.AlertDialog.new(f"Delete '{item.path.name}'?")
        dialog.set_body("This file will be permanently deleted. This action cannot be undone.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_delete_dialog_response, item)
        dialog.present(self.window)

    def _on_delete_dialog_response(self, dialog, response, item):
        """Handles the response from the delete confirmation dialog."""
        if response == "delete":
            try:
                item.path.unlink()
                self._load_wallpapers_async()
                self.toast_overlay.add_toast(Adw.Toast.new(f"'{item.path.name}' deleted."))
            except OSError as e:
                self.toast_overlay.add_toast(Adw.Toast.new(f"Error deleting file: {e}"))

    def _format_size(self, size_bytes):
        """Formats a file size in bytes to a human-readable string."""
        if size_bytes == 0: return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def _on_show_properties_activated(self, action, param):
        """Handles the 'Properties' action from the context menu by showing a dialog."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        try:
            stat_info = item.path.stat()
            file_size = self._format_size(stat_info.st_size)
            mod_time = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            file_type = item.path.suffix.upper()[1:] + " File"
            dialog = Adw.AlertDialog.new()
            dialog.set_heading(f"Properties for '{item.path.name}'")
            content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
            
            def add_property_row(label_text, value_text):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                label = Gtk.Label(label=f"<b>{label_text}:</b>", use_markup=True, halign=Gtk.Align.START)
                value = Gtk.Label(label=str(value_text), halign=Gtk.Align.START, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
                row.append(label)
                row.append(value)
                content_box.append(row)

            add_property_row("Type", file_type)
            add_property_row("Path", str(item.path.parent))
            add_property_row("Size", file_size)
            add_property_row("Last Modified", mod_time)

            if item.path.suffix.lower() in SUPPORTED_STATIC:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(item.path))
                    add_property_row("Resolution", f"{pixbuf.get_width()}x{pixbuf.get_height()}")
                except GLib.Error as e:
                    print(f"Could not get image properties for {item.path.name}: {e}")
            elif item.path.suffix.lower() in (SUPPORTED_LIVE + ['.gif']):
                try:
                    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', str(item.path)]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    media_info = json.loads(result.stdout)
                    
                    if 'format' in media_info and 'duration' in media_info['format']:
                        duration_s = float(media_info['format']['duration'])
                        seconds = int(duration_s % 60)
                        minutes = int((duration_s // 60) % 60)
                        hours = int(duration_s // 3600)
                        if hours > 0:
                            add_property_row("Duration", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                        else:
                            add_property_row("Duration", f"{minutes:02d}:{seconds:02d}")
                    if 'streams' in media_info and media_info['streams']:
                        stream = media_info['streams'][0]
                        if 'width' in stream and 'height' in stream:
                            add_property_row("Resolution", f"{stream['width']}x{stream['height']}")
                        if 'r_frame_rate' in stream:
                            num, den = map(int, stream['r_frame_rate'].split('/'))
                            if den != 0:
                                add_property_row("Frame Rate", f"{round(num/den, 2)} fps")
                        if 'bit_rate' in stream:
                             add_property_row("Bit Rate", f"{self._format_size(int(stream['bit_rate']))}/s")
                        elif 'bit_rate' in media_info.get('format', {}):
                             add_property_row("Bit Rate", f"{self._format_size(int(media_info['format']['bit_rate']))}/s")
                except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
                    print(f"Could not get media properties for {item.path.name}: {e}")
            dialog.set_extra_child(content_box)
            dialog.add_response("close", "Close")
            dialog.set_default_response("close")
            dialog.present(self.window)
        except FileNotFoundError:
            self.toast_overlay.add_toast(Adw.Toast.new("File not found."))
        except Exception as e:
            self.toast_overlay.add_toast(Adw.Toast.new(f"Could not get properties: {e}"))

    def _wallpaper_filter_func(self, item):
        """Filter function for static wallpapers."""
        if not self.search_text: return True
        return self.search_text.lower() in item.path.name.lower()

    def _live_wallpaper_filter_func(self, item):
        """Filter function for live wallpapers."""
        backend = self.settings.get_string('live-backend')
        if backend == 'swww' and item.path.suffix.lower() != '.gif':
            return False
        if self.search_text and self.search_text.lower() not in item.path.name.lower():
            return False
        if self.hide_original_after_recode and '_recoded' not in item.path.name:
            wallpaper_dir = self.settings.get_string('wallpaper-dir')
            recoded_path = Path(wallpaper_dir) / 'recoded' / f"{item.path.stem}_recoded{item.path.suffix}"
            if recoded_path.exists():
                return False
        return True

    def _on_search_changed(self, search_entry):
        """Handles changes in the search entry text."""
        self.search_text = search_entry.get_text()
        self.static_filter.changed(Gtk.FilterChange.DIFFERENT)
        self.live_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_status_page_visibility()
        self._update_random_button_visibility()

    def _update_status_page_visibility(self):
        """Shows or hides the 'No Results' page."""
        is_searching = bool(self.search_text)
        current_view = self.view_stack.get_visible_child_name()
        
        if current_view in ['static', 'live']:
            model = self.static_view.get_model() if current_view == 'static' else self.live_view.get_model()
            show_status = is_searching and model and model.get_n_items() == 0
            self.status_page.set_visible(show_status)
        else:
            self.status_page.set_visible(False)

    def _prompt_directory(self, button):
        """Opens a dialog to select the wallpaper directory."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Select Wallpaper Directory")
        dialog.select_folder(self.window, None, self._on_select_folder_finish, None)

    def _on_select_folder_finish(self, source, result, _):
        """Handles the result of the folder selection dialog."""
        try:
            folder = source.select_folder_finish(result)
            if folder:
                self.settings.set_string('wallpaper-dir', folder.get_path())
                self._load_wallpapers_async()
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print(f"Error selecting folder: {e.message}")

    def _on_clear_cache_clicked(self, button):
        """Clears the thumbnail cache."""
        dialog = Adw.AlertDialog.new("Clear Cache?")
        dialog.set_body("All cached thumbnails will be deleted. This action cannot be undone.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_clear_cache_dialog_response)
        dialog.present(self.window)

    def _on_clear_cache_dialog_response(self, dialog, response):
        if response == "clear":
            for f in self.cache_dir.glob('*'):
                try: f.unlink()
                except OSError as e: print(f"Error deleting cache file {f}: {e}")
            self.texture_cache.clear()
            self.toast_overlay.add_toast(Adw.Toast.new("Thumbnail cache cleared"))
            # Force a complete refresh of the live view
            self.live_store.splice(0, self.live_store.get_n_items(), [])
            self._load_wallpapers_async()

    def _on_reload_css_clicked(self, button):
        """Reloads the custom CSS."""
        self._update_css()
        self.toast_overlay.add_toast(Adw.Toast.new("CSS reloaded"))

    def _on_corner_radius_changed(self, adjustment):
        """Handles changes to the corner radius setting."""
        self.corner_radius = int(adjustment.get_value())
        self.settings.set_int('corner-radius', self.corner_radius)
        self._update_corner_radius_css()

    def _on_show_labels_toggled(self, switch, _):
        """Handles toggling the visibility of item labels."""
        self.show_labels = switch.get_active()
        self.settings.set_boolean('show-labels', self.show_labels)
        self._emit_preview_size_changed()

    def _on_hide_original_toggled(self, switch, _):
        """Handles toggling the visibility of original files after recoding."""
        self.hide_original_after_recode = switch.get_active()
        self.settings.set_boolean('hide-original-after-recode', self.hide_original_after_recode)
        self.live_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_mpv_socket_path_changed(self, entry_row):
        """Handles changes to the mpv socket path."""
        new_path = entry_row.get_text()
        self.mpv_socket_path = new_path
        self.settings.set_string('mpv-socket-path', new_path)
        self.toast_overlay.add_toast(Adw.Toast.new("mpv socket path updated. Restart live wallpaper to apply."))

    def _on_enable_sound_toggled(self, switch, _):
        """Handles toggling the video sound setting."""
        self.enable_video_sound = switch.get_active()
        self.settings.set_boolean('enable-video-sound', self.enable_video_sound)
        self.send_mpv_command(["set_property", "mute", "no" if self.enable_video_sound else "yes"])

    def _on_video_volume_changed(self, adjustment):
        """Handles changes to the video volume setting."""
        self.video_volume = int(adjustment.get_value())
        self.settings.set_int('video-volume', self.video_volume)
        self.send_mpv_command(["set_property", "volume", self.video_volume])
        if self.prefs_window.volume_label:
            self.prefs_window.volume_label.set_text(f"{self.video_volume}%")

    def _on_swww_transition_type_changed(self, combo, _):
        """Handles changes to the swww transition type."""
        model = combo.get_model()
        self.swww_transition_type = model.get_string(combo.get_selected())
        self.settings.set_string('swww-transition-type', self.swww_transition_type)

    def _on_swww_duration_changed(self, adjustment):
        """Handles changes to the swww transition duration."""
        self.swww_transition_duration = int(adjustment.get_value())
        self.settings.set_int('swww-transition-duration', self.swww_transition_duration)

    def _on_swww_fill_type_changed(self, combo, _):
        """Handles changes to the swww fill type."""
        model = combo.get_model()
        self.swww_fill_type = model.get_string(combo.get_selected())
        self.settings.set_string('swww-fill-type', self.swww_fill_type)

    def _on_swww_fps_changed(self, adjustment):
        """Handles changes to the swww transition fps."""
        self.swww_transition_fps = int(adjustment.get_value())
        self.settings.set_int('swww-transition-fps', self.swww_transition_fps)

    def _on_recode_all_clicked(self, button):
        """Shows a confirmation dialog before starting a batch recode."""
        dialog = Adw.AlertDialog.new("Recode all videos?")
        dialog.set_body("This will recode all videos with a resolution higher than your display. This may take a long time and consume significant CPU resources. Original files will not be modified.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("recode", "Recode All")
        dialog.set_response_appearance("recode", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_recode_all_dialog_response)
        dialog.present(self.window)

    def _on_recode_all_dialog_response(self, dialog, response):
        """Handles the response from the batch recode confirmation dialog."""
        if response == "recode":
            self.toast_overlay.add_toast(Adw.Toast.new("Starting batch recode..."))
            thread = threading.Thread(target=self._recode_all_thread, args=(self.window,), daemon=True)
            thread.start()

    def _recode_all_thread(self, window):
        """Identifies and adds high-resolution videos to the queue."""
        monitor_width, monitor_height = get_monitor_resolution(window)
        if not monitor_width or not monitor_height:
            GLib.idle_add(self.toast_overlay.add_toast, Adw.Toast.new("Error: Could not determine display resolution for batch recode."))
            return
        items_to_process = [self.live_store.get_item(i) for i in range(self.live_store.get_n_items())]
        queued_count = 0
        for item in items_to_process:
            path = item.path
            recoded_path = path.with_name(f"{item.path.stem}_recoded{item.path.suffix}")
            with self.recode_lock:
                already_queued = item in self.recode_queue or self.recode_currently_running == item
            if recoded_path.exists() or '_recoded' in path.name or already_queued:
                continue
            try:
                cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', str(path)]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                video_width, video_height = map(int, result.stdout.strip().split('x'))
                if video_width > monitor_width or video_height > monitor_height:
                    with self.recode_lock:
                        self.recode_queue.append(item)
                    queued_count += 1
            except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as e:
                print(f"Could not process {path.name} for batch recode: {e}")
                continue
        if queued_count > 0:
            GLib.idle_add(self.toast_overlay.add_toast, Adw.Toast.new(f"Added {queued_count} videos to the recode queue."))
            GLib.idle_add(self._start_next_recode_if_possible)

    def _on_scroll_step_changed(self, adjustment):
        """Handles changes to the zoom scroll step."""
        self.scroll_step = int(adjustment.get_value())
        self.settings.set_int('scroll-step', self.scroll_step)
        if self.preview_adjustment:
            self.preview_adjustment.set_step_increment(self.scroll_step)
            self.preview_adjustment.set_page_increment(self.scroll_step)

    def _on_preview_adjustment_changed(self, adjustment):
        """Handles changes to the preview size."""
        self.preview_size = int(adjustment.get_value())
        self.settings.set_int('preview-size', self.preview_size)
        self.texture_cache.clear()
        self._emit_preview_size_changed()
        
    def _on_scroll_resize(self, controller, dx, dy):
        """Handles zooming with Ctrl+Scroll."""
        if not (controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK):
            return False
        if not self.preview_adjustment: return True
        current_value = self.preview_adjustment.get_value()
        new_value = current_value - dy * self.scroll_step
        self.preview_adjustment.set_value(max(self.preview_adjustment.get_lower(), min(new_value, self.preview_adjustment.get_upper())))
        return True

    def _emit_preview_size_changed(self):
        """Emits the preview-size-changed signal for all items."""
        for store in [self.static_store, self.live_store]:
            for i in range(store.get_n_items()):
                store.get_item(i).emit('preview-size-changed')
                
# --- Entry Point ---
if __name__ == '__main__':
    app = Manpaper()
    app.run(sys.argv)