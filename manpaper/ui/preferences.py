import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib

from ..utils import is_backend_installed

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

            mpv_fill_types = ["Fit", "Crop"]
            row_mpv_fill_type = Adw.ComboRow(title="Fill Type", subtitle="How the video should fill the screen", model=Gtk.StringList.new(mpv_fill_types))
            current_mpv_fill = self.settings.get_string('mpvpaper-fill-type')
            try:
                row_mpv_fill_type.set_selected(mpv_fill_types.index(current_mpv_fill))
            except ValueError:
                row_mpv_fill_type.set_selected(0) # Default to Fit
            row_mpv_fill_type.connect('notify::selected', self.app._on_mpvpaper_fill_type_changed)
            video_group.add(row_mpv_fill_type)

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
