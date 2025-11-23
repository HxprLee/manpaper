import os
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
import hashlib
import requests

# Required GTK and Adwaita versions
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gsk', '4.0')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango, GdkPixbuf, Gsk

from .config import SUPPORTED_STATIC, SUPPORTED_LIVE
from .data_models import RecodeQueueItem, WallpaperItem, OnlineWallpaperItem, DownloadQueueItem
from .online import search_wallhaven
from .ui.preferences import PreferencesWindow
from .ui.window import MainWindow
from .ui.dialogs import (
    create_confirmation_dialog, create_url_input_dialog,
    create_properties_dialog, create_online_properties_dialog,
    create_about_dialog, create_shortcuts_window
)
from .utils import (
    is_backend_installed, get_monitor_refresh_rate, get_monitor_resolution, 
    get_monitor_aspect_ratio, kill_backend_processes, build_command
)

# --- Main Application Class ---
class Manpaper(Adw.Application):
    """The main application class for Manpaper."""
    def __init__(self):
        super().__init__(application_id='io.hxprlee.Manpaper', flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect('shutdown', self._on_shutdown)
        Adw.init()
        self.settings = Gio.Settings.new('io.hxprlee.Manpaper')
        self.window = None

        self.search_text = ""
        self.online_search_text = ""
        self.online_current_page = 1
        self.online_resolution_text = ""
        self.online_atleast_text = ""
        self.online_ratio_text = ""
        self.right_clicked_item = None
        self.mpv_process = None

        self.static_store = Gio.ListStore.new(WallpaperItem)
        self.static_filter = Gtk.CustomFilter.new(self._wallpaper_filter_func)
        self.static_model = Gtk.SingleSelection.new(Gtk.FilterListModel.new(self.static_store, self.static_filter))
        
        self.live_store = Gio.ListStore.new(WallpaperItem)
        self.live_filter = Gtk.CustomFilter.new(self._live_wallpaper_filter_func)
        self.live_model = Gtk.SingleSelection.new(Gtk.FilterListModel.new(self.live_store, self.live_filter))

        self.online_store = Gio.ListStore.new(OnlineWallpaperItem)
        # self.online_filter = Gtk.CustomFilter.new(self._online_wallpaper_filter_func)
        # self.online_model = Gtk.SingleSelection.new(Gtk.FilterListModel.new(self.online_store, self.online_filter))
        self.online_model = Gtk.SingleSelection.new(self.online_store)


        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, spinning=False, visible=False)
        
        self.recode_queue = []
        self.recode_currently_running = None
        self.recode_lock = threading.Lock()
        self.recode_process = None
        self.recode_popover_store = Gio.ListStore.new(RecodeQueueItem)
        # self.active_downloads = {} # Remove this

        self.download_popover_store = Gio.ListStore.new(DownloadQueueItem)


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
        self.mpvpaper_fill_type = self.settings.get_string('mpvpaper-fill-type')
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
        


        self.zen_mode_active = False
        self.original_show_labels = self.show_labels

        self.prefs_window = PreferencesWindow(self)

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def do_activate(self):
        if not self.window:
            self.window = MainWindow(self)

        self._check_and_set_default_backends()
        self.window.view_stack.connect('notify::visible-child-name', self._on_view_changed)
        self._load_wallpapers_async()
        self._setup_actions()
        self._setup_key_controller()

        self.window.present()

    def _on_shutdown(self, app):
        """Clean up resources on application exit."""
        # The mpvpaper process is no longer terminated here to allow it to persist.
        pass

    def run_in_background(self, target_func, callback_func, *args, **kwargs):
        """Helper to run a function in a background thread using GTask."""
        task = Gio.Task.new(self, None, callback_func, None)
        
        # We need to capture args and kwargs to pass to the target function
        task.target_func = target_func
        task.args = args
        task.kwargs = kwargs

        def worker_func(task, source_object, task_data, cancellable):
            try:
                # Execute the blocking function
                result = task.target_func(*task.args, **task.kwargs)
                
                # We can't easily pass arbitrary Python objects through return_value 
                # if they aren't GObjects. So we attach the result to the task object itself.
                task.python_result = result
                task.python_error = None
                task.return_boolean(True)
            except Exception as e:
                task.python_result = None
                task.python_error = e
                task.return_boolean(False)
                
        task.run_in_thread(worker_func)

    def send_mpv_command(self, command):
        """Sends a JSON IPC command to the mpv socket using socat."""
        if not self.mpv_socket_path:
            return
        
        if not is_backend_installed('socat'):
            if self.window.toast_overlay:
                GLib.idle_add(self.window.toast_overlay.add_toast, Adw.Toast.new("socat is not installed. IPC commands cannot be sent."))
            return

        try:
            socket_file = Path(self.mpv_socket_path).expanduser()
            if not socket_file.is_socket():
                return

            command_str = json.dumps({"command": command})
            subprocess.Popen(f"echo '{command_str}' | socat - '{socket_file}'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Failed to send command to mpv socket: {e}")



    def _update_url_title(self, item, new_title):
        """Updates the title of a URL-based wallpaper."""
        print(f"DEBUG: _update_url_title called with new_title='{new_title}', old_title='{item.title}'")
        
        try:
            # Load existing bookmarks
            bookmarks_str = self.settings.get_string('video-bookmarks')
            bookmarks = json.loads(bookmarks_str)
        except (json.JSONDecodeError, TypeError):
            bookmarks = []
        
        # Find and update the bookmark
        for bookmark in bookmarks:
            if bookmark.get('url') == item.path:
                bookmark['title'] = new_title
                print(f"DEBUG: Found and updated bookmark for {item.path}")
                break
        
        # Save updated bookmarks
        self.settings.set_string('video-bookmarks', json.dumps(bookmarks))
        
        # Update the item's title directly (no need to reload entire list)
        item.title = new_title
        
        # Notify the list model that the item changed
        # This will update the UI without reloading everything
        for i in range(self.live_store.get_n_items()):
            if self.live_store.get_item(i) == item:
                self.live_store.items_changed(i, 1, 1)
                break
        
        # Show confirmation toast
        self.window.toast_overlay.add_toast(Adw.Toast.new(f"Title updated to: {new_title}"))



    def _on_add_local_clicked(self, action, param):
        """Opens a file dialog to add local video files."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Add Local Video Files")
        dialog.set_modal(True)
        dialog.set_accept_label("Add")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter.new()
        video_filter.set_name("Video Files")
        for ext in SUPPORTED_LIVE:
            video_filter.add_pattern(f"*{ext}")
        filters.append(video_filter)
        dialog.set_filters(filters)

        dialog.open_multiple(self.window, None, self._on_add_local_files_finish)

    def _on_add_local_files_finish(self, dialog, result):
        """Handles the result of the file selection dialog."""
        try:
            files = dialog.open_multiple_finish(result)
            if not files:
                return

            wallpaper_dir_str = self.settings.get_string('wallpaper-dir')
            if not wallpaper_dir_str:
                self.window.toast_overlay.add_toast(Adw.Toast.new("Wallpaper directory not set."))
                return

            wallpaper_dir = Path(wallpaper_dir_str)
            if not wallpaper_dir.is_dir():
                self.window.toast_overlay.add_toast(Adw.Toast.new("Wallpaper directory not found."))
                return

            added_count = 0
            for file in files:
                try:
                    source_path = Path(file.get_path())
                    destination_path = wallpaper_dir / source_path.name
                    if not destination_path.exists():
                        source_path.rename(destination_path)
                        added_count += 1
                except Exception as e:
                    self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error moving file: {e}"))

            if added_count > 0:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Added {added_count} new wallpaper(s)."))
                self._load_wallpapers_async()

        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error selecting files: {e.message}"))

    def _on_add_url_clicked(self, action, param):
        dialog = create_url_input_dialog(self.window, self._on_add_url_dialog_response)
        dialog.present(self.window)


    def _on_add_url_dialog_response(self, dialog, response_id):
        if response_id == "add" or response_id == "download":
            # Access the url_entry stored on the dialog object
            url = dialog.url_entry.get_text().strip()
            if url:
                # Validate that it's a valid YouTube URL
                if 'youtube.com' in url or 'youtu.be' in url:
                    if url.startswith("http://") or url.startswith("https://"):
                        if response_id == "add":
                            # Stream directly without downloading
                            self._add_url_wallpaper_stream(url)
                        else:  # download
                            # Download the video
                            self._download_youtube_video(url)
                    else:
                        self.window.toast_overlay.add_toast(Adw.Toast.new("URL must start with http:// or https://"))
                else:
                    self.window.toast_overlay.add_toast(Adw.Toast.new("Only YouTube URLs are supported."))




    def _add_url_wallpaper_stream(self, url):
        """Adds a YouTube URL for direct streaming (original behavior)."""
        # Check if yt-dlp is installed
        if not is_backend_installed('yt-dlp'):
            self.window.toast_overlay.add_toast(Adw.Toast.new("yt-dlp is not installed. Please install it to use YouTube videos."))
            return
        
        try:
            bookmarks_str = self.settings.get_string('video-bookmarks')
            bookmarks = json.loads(bookmarks_str)
        except (json.JSONDecodeError, TypeError):
            bookmarks = []

        if any(b.get('url') == url for b in bookmarks):
            self.window.toast_overlay.add_toast(Adw.Toast.new("URL already exists."))
            return
        
        # Fetch video title using yt-dlp in background
        self.window.toast_overlay.add_toast(Adw.Toast.new("Fetching video information..."))
        
        def fetch_title_worker(url_to_fetch):
            # Get video info as JSON
            command = ['yt-dlp', '--dump-json', '--no-download', url_to_fetch]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            
            # Parse JSON response
            video_info = json.loads(result.stdout)
            title = video_info.get('title', url_to_fetch)
            return url_to_fetch, title

        def on_fetch_title_complete(source, result, data):
            try:
                success = result.propagate_boolean()
                if success:
                    url_res, title_res = result.python_result
                    self._add_streaming_bookmark(url_res, title_res, bookmarks)
                else:
                    # Fallback to URL if yt-dlp fails (captured in worker exception)
                    print(f"Fetch title failed: {result.python_error}")
                    self._add_streaming_bookmark(url, url, bookmarks)
            except Exception as e:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error fetching title: {str(e)}"))
                self._add_streaming_bookmark(url, url, bookmarks)

        self.run_in_background(fetch_title_worker, on_fetch_title_complete, url)
    
    def _add_streaming_bookmark(self, url, title, bookmarks):
        """Adds streaming bookmark with title to settings."""
        new_bookmark = {"url": url, "title": title}
        bookmarks.append(new_bookmark)
        self.settings.set_string('video-bookmarks', json.dumps(bookmarks))
        
        new_item = WallpaperItem(path=url, title=title)
        self.live_store.append(new_item)
        self.window.toast_overlay.add_toast(Adw.Toast.new(f"Added: {title}"))
        return False  # For GLib.idle_add


    def _download_youtube_video(self, url):
        """Downloads a YouTube video at the user's resolution."""

        # Check if yt-dlp is installed
        if not is_backend_installed('yt-dlp'):
            self.window.toast_overlay.add_toast(Adw.Toast.new("yt-dlp is not installed. Please install it to use YouTube videos."))
            return
        
        # Check if URL already exists in bookmarks (already added for streaming)
        try:
            bookmarks_str = self.settings.get_string('video-bookmarks')
            bookmarks = json.loads(bookmarks_str)
        except (json.JSONDecodeError, TypeError):
            bookmarks = []

        if any(b.get('url') == url for b in bookmarks):
            self.window.toast_overlay.add_toast(Adw.Toast.new("This URL is already added for streaming."))
            return
        
        # Get user's monitor resolution
        width, height = get_monitor_resolution(self.window)
        if not width or not height:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Could not detect monitor resolution."))
            return
        
        # Show downloading toast
        self.window.toast_overlay.add_toast(Adw.Toast.new(f"Downloading YouTube video at {width}x{height}..."))
        
        # Download the video in a background thread
        wallpaper_dir_str = self.settings.get_string('wallpaper-dir')
        if not wallpaper_dir_str:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Wallpaper directory not set."))
            return
        
        wallpaper_dir = Path(wallpaper_dir_str)
        if not wallpaper_dir.is_dir():
            self.window.toast_overlay.add_toast(Adw.Toast.new("Wallpaper directory not found."))
            return
        
        def download_worker(url_to_download, wallpaper_dir_path, max_height):
            # Generate a filename from the video ID
            video_id = url_to_download.split('v=')[-1].split('&')[0] if 'v=' in url_to_download else url_to_download.split('/')[-1]
            video_id = video_id.split('?')[0]  # Remove query parameters
            output_path = wallpaper_dir_path / f"yt_{video_id}.mp4"
            
            # First, get video info to extract title
            info_command = ['yt-dlp', '--dump-json', '--no-download', url_to_download]
            info_result = subprocess.run(info_command, capture_output=True, text=True, check=True)
            video_info = json.loads(info_result.stdout)
            title = video_info.get('title', f"yt_{video_id}")
            
            # Download with resolution constraint matching user's display
            # Format: bestvideo[height<=HEIGHT]+bestaudio/best[height<=HEIGHT]
            format_string = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"
            
            command = [
                'yt-dlp',
                '-f', format_string,
                '--merge-output-format', 'mp4',
                '-o', str(output_path),
                url_to_download
            ]
            
            subprocess.run(command, capture_output=True, text=True, check=True)
            return output_path, title

        def on_download_complete(source, result, data):
            try:
                success = result.propagate_boolean()
                if success:
                    path_res, title_res = result.python_result
                    self._on_youtube_download_complete(path_res, title_res)
                else:
                    error_msg = f"Failed to download YouTube video: {result.python_error}"
                    if isinstance(result.python_error, subprocess.CalledProcessError):
                         error_msg = f"Failed to download YouTube video: {result.python_error.stderr[:100] if result.python_error.stderr else str(result.python_error)}"
                    self.window.toast_overlay.add_toast(Adw.Toast.new(error_msg))
            except Exception as e:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error: {str(e)}"))

        self.run_in_background(download_worker, on_download_complete, url, wallpaper_dir, height)
    
    def _on_youtube_download_complete(self, video_path, title):
        """Called after YouTube video download completes."""
        try:
            # Add only the downloaded file to live wallpapers with the YouTube title
            new_item = WallpaperItem(path=video_path, title=title)
            self.live_store.append(new_item)
            
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Downloaded: {title}"))
            self._load_wallpapers_async()  # Refresh to show the new video
        except Exception as e:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error adding video: {e}"))
        
        return False  # For GLib.idle_add




    def _get_online_wallpaper_local_path(self, item):
        """Determines the expected local path for a downloaded online wallpaper."""
        wallpaper_dir_str = self.settings.get_string('wallpaper-dir')
        if not wallpaper_dir_str:
            return None
        
        file_extension = Path(item.full_url).suffix
        file_path = Path(wallpaper_dir_str) / f"{item.wall_id}{file_extension}"
        return file_path if file_path.exists() else None

    def _on_download_wallpaper_clicked(self, button, item):
        """Handles the 'Download' button click for an online wallpaper."""
        print(f"Download button clicked for {item.wall_id}")
        wallpaper_dir_str = self.settings.get_string('wallpaper-dir')
        if not wallpaper_dir_str:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Wallpaper directory not set."))
            return

        # Add to download popover store
        download_queue_item = DownloadQueueItem(f"Downloading {item.wall_id}", "Downloading", item)
        self.download_popover_store.append(download_queue_item)
        self._update_download_ui() # Update the popover UI

        def download_worker(item_to_dl, wallpaper_dir_path):
            print(f"Starting download for {item_to_dl.wall_id} from {item_to_dl.full_url}")
            response = requests.get(item_to_dl.full_url, stream=True)
            response.raise_for_status()
            print(f"Successfully fetched content for {item_to_dl.wall_id}")

            file_extension = Path(item_to_dl.full_url).suffix
            file_path = Path(wallpaper_dir_path) / f"{item_to_dl.wall_id}{file_extension}"
            print(f"Saving {item_to_dl.wall_id} to {file_path}")

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Download and save complete for {item_to_dl.wall_id}")
            return item_to_dl, file_path

        def on_download_complete(source, result, data):
            try:
                success = result.propagate_boolean()
                if success:
                    item_res, path_res = result.python_result
                    self._on_download_finished(item_res, True, path_res, None, download_queue_item)
                else:
                    error_msg = str(result.python_error)
                    self._on_download_finished(item, False, None, error_msg, download_queue_item)
            except Exception as e:
                self._on_download_finished(item, False, None, str(e), download_queue_item)

        self.run_in_background(download_worker, on_download_complete, item, wallpaper_dir_str)

    def _on_apply_downloaded_wallpaper_clicked(self, button, item):
        """Handles the 'Apply' button click for a downloaded online wallpaper."""
        print(f"Apply button clicked for downloaded wallpaper {item.wall_id} at {item.local_path}")
        if item.local_path and os.path.exists(item.local_path):
            wallpaper_item = WallpaperItem(Path(item.local_path), title=item.title)
            self._set_wallpaper(wallpaper_item)
        else:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Downloaded wallpaper not found: {item.title}"))

    def _on_delete_wallpaper_clicked(self, button, item):
        """Handles the 'Delete' button click for a downloaded online wallpaper."""
        print(f"Delete button clicked for {item.wall_id}")
        if item.local_path and os.path.exists(item.local_path):
            try:
                os.remove(item.local_path)
                item.is_downloaded = False
                item.local_path = None
                item.emit('download-status-changed', False, "")
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper {item.wall_id} deleted."))
                self._load_wallpapers_async() # Reload to update UI
            except OSError as e:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error deleting wallpaper: {e}"))
        else:
            # It might be already deleted or path is wrong, just reset state
            item.is_downloaded = False
            item.local_path = None
            item.emit('download-status-changed', False, "")
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper file not found, status reset."))


    def _on_download_finished(self, item, success, file_path=None, error_message=None, download_queue_item=None):
        """Callback after a wallpaper download is finished."""
        print(f"DEBUG: _on_download_finished called for {item.wall_id}, success={success}")
        # Remove from download popover store
        if download_queue_item:
            for i in range(self.download_popover_store.get_n_items()):
                if self.download_popover_store.get_item(i) == download_queue_item:
                    self.download_popover_store.remove(i)
                    break
        self._update_download_ui() # Update the popover UI

        if success:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper {item.wall_id} downloaded."))
            item.is_downloaded = True
            item.local_path = str(file_path)
            item.emit('download-status-changed', True, str(file_path))
            self._load_wallpapers_async() # Reload after callback to ensure UI is updated
        else:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Failed to download {item.wall_id}: {error_message}"))

    def _load_online_thumbnail(self, item, picture):
        """Loads an online thumbnail in a background thread."""
        
        def load_thumbnail_worker(item_to_load):
            print(f"Attempting to download thumbnail from: {item_to_load.thumbnail_url}")
            response = requests.get(item_to_load.thumbnail_url)
            response.raise_for_status()
            print(f"Thumbnail downloaded successfully for {item_to_load.wall_id}")
            
            # Return the raw bytes, create texture on main thread
            return item_to_load, response.content

        def on_load_thumbnail_complete(source, result, data):
            try:
                success = result.propagate_boolean()
                if success:
                    item_res, content_bytes = result.python_result
                    
                    # Create a pixbuf from the downloaded data
                    bytes_glib = GLib.Bytes.new(content_bytes)
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(bytes_glib.get_data())
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    
                    # Create a texture from the pixbuf
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    picture.set_paintable(texture)
                    print(f"Set paintable for {item_res.wall_id}")
                else:
                    print(f"Error loading thumbnail for {item.wall_id}: {result.python_error}")
            except Exception as e:
                print(f"Error processing thumbnail for {item.wall_id}: {e}")

        self.run_in_background(load_thumbnail_worker, on_load_thumbnail_complete, item)

    # _load_online_thumbnail_thread removed as it is now inline




    def _setup_actions(self):
        """Sets up application actions and menu."""
        menu_model = Gio.Menu()
        menu_model.append("Zen Mode", "app.zen_mode")
        menu_model.append("Keyboard Shortcuts", "app.shortcuts")
        menu_model.append("About", "app.about")
        self.window.menu_popover.set_menu_model(menu_model)

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

        action_add_url = Gio.SimpleAction(name="add_url")
        action_add_url.connect("activate", self._on_add_url_clicked)
        self.add_action(action_add_url)

        action_add_local = Gio.SimpleAction(name="add_local")
        action_add_local.connect("activate", self._on_add_local_clicked)
        self.add_action(action_add_local)

        action_download_online = Gio.SimpleAction(name="download_online_wallpaper")
        action_download_online.connect("activate", self._on_download_online_wallpaper_activated)
        self.add_action(action_download_online)

        action_show_online_properties = Gio.SimpleAction(name="show_online_properties")
        action_show_online_properties.connect("activate", self._on_show_online_properties_activated)
        self.add_action(action_show_online_properties)

        action_delete_online = Gio.SimpleAction(name="delete_online_wallpaper")
        action_delete_online.connect("activate", self._on_delete_online_wallpaper_activated)
        self.add_action(action_delete_online)

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
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Static backend '{current_static}' not found. Defaulting to '{new_default}'."))
            self.settings.set_string('static-backend', new_default)
        elif not installed_static:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Warning: No static wallpaper backends found."))

        all_live = ['swww', 'mpvpaper']
        installed_live = [b for b in all_live if is_backend_installed(b)]
        current_live = self.settings.get_string('live-backend')

        if installed_live and current_live not in installed_live:
            new_default = installed_live[0]
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Live backend '{current_live}' not found. Defaulting to '{new_default}'."))
            self.settings.set_string('live-backend', new_default)
        elif not installed_live:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Warning: No live wallpaper backends found."))

    def _update_css(self):
        """Loads default and custom CSS."""
        default_css = '''
            .main-content { box-shadow: inset 0 -4px 8px -4px rgba(0, 0, 0, 0.2); }
            .pill-revealer { border-radius: 28px; }
            gridview.view { background-color: transparent; }
            
            .recode-item { background-color: alpha(@theme_fg_color, 0.05); border-radius: 8px; }
            .scrolled-list { color: transparent; border-radius: 16px; }
            .drop-shadow {
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            }
            .resolution-label {
                background-color: rgba(0, 0, 0, 0.5);
                color: white;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 0.8em;
            }
        '''
        self.css_provider.load_from_string(default_css)

        display = Gdk.Display.get_default()
        Gtk.StyleContext.remove_provider_for_display(display, self.custom_css_provider)

        if self.use_custom_css and self.custom_css_path and Path(self.custom_css_path).exists():
            try:
                self.custom_css_provider.load_from_path(self.custom_css_path)
                Gtk.StyleContext.add_provider_for_display(display, self.custom_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            except Exception as e:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error loading custom CSS: {e}"))

    def _update_corner_radius_css(self):
        """Updates the CSS for wallpaper preview corner radius."""
        css = f"picture {{ border-radius: {self.corner_radius}px; }}"
        self.corner_radius_css_provider.load_from_string(css)
        
    def _on_search_toggled(self, button):
        """Handles the toggling of the search button."""
        is_active = button.get_active()
        self.window.search_button_revealer.set_reveal_child(not is_active)
        self.window.title_stack.set_visible_child_name("search" if is_active else "switcher")
        self.window.fade_revealer.set_reveal_child(False)
        GLib.timeout_add(100, lambda: self.window.fade_revealer.set_reveal_child(True))
        if is_active:
            self.window.search_entry.grab_focus()
        else:
            self.window.search_entry.set_text("")
            self.window.set_focus(None)
        self._update_random_button_visibility()

    def _update_random_button_visibility(self):
        """Shows or hides the random button based on context."""
        visible_child = self.window.view_stack.get_visible_child_name()
        is_prefs = visible_child == "preferences"
        is_online = visible_child == "online"
        is_searching = bool(self.search_text)
        if self.window.random_button:
            self.window.random_button.get_parent().set_reveal_child(not is_prefs and not is_online and not is_searching and not self.zen_mode_active)

    def _update_add_url_button_visibility(self):
        """Shows or hides the Add URL button based on context."""
        is_live_view = self.window.view_stack.get_visible_child_name() == "live"
        if self.window.add_button_revealer:
            self.window.add_button_revealer.set_reveal_child(is_live_view and not self.zen_mode_active)

    def _hide_search_revealer_if_needed(self):
        """Callback to hide the search revealer if still in prefs."""
        if self.window.view_stack.get_visible_child_name() == "preferences":
            self.window.search_button_revealer.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _on_view_changed(self, stack, _):
        """Handles view changes in the main stack."""
        self._update_random_button_visibility()
        self._update_add_url_button_visibility()
        is_prefs = stack.get_visible_child_name() == "preferences"
        is_online = stack.get_visible_child_name() == "online"
        # self.purity_revealer.set_reveal_child(is_online) # Removed, now controlled by filter button
        self.window.filter_button_revealer.set_reveal_child(is_online) # Control new filter button
        self.window.load_more_button_revealer.set_reveal_child(is_online) # Control load more button
        if is_online:
            self._trigger_online_search(latest=True)

        if is_prefs:
            self.window.search_button_revealer.set_reveal_child(False)
            GLib.timeout_add(300, self._hide_search_revealer_if_needed)
        else:
            self.window.search_button_revealer.set_visible(True)
            self.window.search_button_revealer.set_reveal_child(True)

        self.window.fade_revealer.set_reveal_child(False)
        GLib.timeout_add(100, lambda: (
            self.window.slide_revealer.set_reveal_child(not is_prefs),
            GLib.timeout_add(50, lambda: (self.window.fade_revealer.set_reveal_child(True), GLib.SOURCE_REMOVE)[1]),
            GLib.SOURCE_REMOVE
        )[2])

        if is_prefs and self.window.search_button.get_active():
            self.window.search_button.set_active(False)

    def _on_zen_mode_toggled(self, *args):
        """Toggles Zen mode, hiding UI elements."""
        if self.window.menu_popover.is_visible():
            self.window.menu_popover.popdown()
        self.zen_mode_active = not self.zen_mode_active

        print(f"Zen Mode Toggled. zen_mode_active: {self.zen_mode_active}")
        print(f"  Initial self.show_labels: {self.show_labels}")

        self.window.header_revealer.set_reveal_child(not self.zen_mode_active)
        self._update_random_button_visibility()
        self._update_add_url_button_visibility()
        self.window.filter_button_revealer.set_reveal_child(not self.zen_mode_active) # Hide/show filter button

        # Directly manage self.show_labels and then emit the signal
        if self.zen_mode_active:
            self.original_show_labels = self.show_labels
            if self.show_labels:
                self.show_labels = False # Directly set to False
                self.settings.set_boolean('show-labels', False) # Update settings
        elif self.original_show_labels and not self.show_labels:
            self.show_labels = True # Directly set to True
            self.settings.set_boolean('show-labels', True) # Update settings
        
        self._update_status_page_visibility()
        print(f"  Final self.show_labels before emit: {self.show_labels}")
        self._emit_preview_size_changed() # Emit once after state is finalized
        print(f"  _emit_preview_size_changed called.")

    def _on_shortcuts_clicked(self, *args):
        """Shows the shortcuts window."""
        self.window.menu_popover.popdown()
        shortcuts_window = create_shortcuts_window(self.window)
        shortcuts_window.present()


    def _on_about_clicked(self, *args):
        """Shows the about dialog."""
        self.window.menu_popover.popdown()
        dialog = create_about_dialog(self.window)
        dialog.present(self.window)


    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handles global key presses."""
        if keyval == Gdk.KEY_Escape and self.window.search_button.get_active():
            self.window.search_button.set_active(False)
            return True
            
        if state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_f:
            if self.window.view_stack.get_visible_child_name() != 'preferences':
                self.window.search_button.set_active(not self.window.search_button.get_active())
                return True
        elif state & Gdk.ModifierType.ALT_MASK:
            key_map = {Gdk.KEY_1: 'static', Gdk.KEY_2: 'live', Gdk.KEY_3: 'online', Gdk.KEY_4: 'preferences'}
            if keyval in key_map:
                self.window.view_stack.set_visible_child_name(key_map[keyval])
                return True
            elif keyval == Gdk.KEY_z:
                self._on_zen_mode_toggled()
                return True
        return False

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
        is_url = isinstance(item.path, str)

        if not is_url and item.path.suffix.lower() in SUPPORTED_STATIC:
            return str(item.path)

        if is_url or item.path.suffix.lower() in SUPPORTED_LIVE:
            if is_url:
                url_hash = hashlib.sha1(item.path.encode()).hexdigest()
                thumb_path = self.cache_dir / (url_hash + '_thumb.jpg')
            else:
                thumb_path = self.cache_dir / (item.path.stem + '_thumb.jpg')
            
            if thumb_path.exists():
                if is_url or thumb_path.stat().st_mtime >= item.path.stat().st_mtime:
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
        """Runs thumbnailer in a background thread."""
        try:
            command = []
            is_url = isinstance(item.path, str)

            if is_url:
                if 'youtube.com' in item.path or 'youtu.be' in item.path:
                    if not is_backend_installed('yt-dlp'):
                        raise FileNotFoundError("yt-dlp is not installed for YouTube URL.")
                    
                    output_template = str(thumb_path.with_suffix(''))
                    command = [
                        'yt-dlp',
                        '--skip-download',
                        '--write-thumbnail',
                        '--convert-thumbnails', 'jpg',
                        '-o', output_template,
                        str(item.path)
                    ]
                else:
                    raise NotImplementedError("Thumbnail generation for non-YouTube URLs is not supported yet.")
            else: # It's a local file
                command = [
                    'ffmpegthumbnailer', '-i', str(item.path), '-o', str(thumb_path),
                    '-s', '256', '-q', '5'
                ]

            if not command:
                raise Exception("Could not determine thumbnailer command.")

            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            GLib.idle_add(self._on_thumbnail_generated, item)

        except Exception as e:
            name = item.path if isinstance(item.path, str) else item.path.name
            print(f"Thumbnail generation failed for {name}: {e}")
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
                # Re-fetch the item from the store to ensure we have the latest version,
                # then update its title property if it exists in the bookmarks.
                live_item = self.live_store.get_item(i)
                try:
                    bookmarks_str = self.settings.get_string('video-bookmarks')
                    bookmarks = json.loads(bookmarks_str)
                    for b in bookmarks:
                        if b.get('url') == live_item.path:
                            live_item.props.title = b.get('title')
                            break
                except (json.JSONDecodeError, TypeError):
                    pass
                # Splicing with a new item is a robust way to signal a change
                new_item = WallpaperItem(path=live_item.path, title=live_item.title)
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
            GLib.idle_add(self._on_wallpapers_loaded, [], [], [])
            return
        root = Path(wallpaper_dir)
        if not root.is_dir():
            GLib.idle_add(self._on_wallpapers_loaded, [], [], [])
            return
        static_paths = [p for p in root.rglob('*') if p.suffix.lower() in SUPPORTED_STATIC]
        live_paths = [p for p in root.rglob('*') if p.suffix.lower() in SUPPORTED_LIVE]
        video_bookmarks_str = self.settings.get_string('video-bookmarks')
        try:
            video_bookmarks = json.loads(video_bookmarks_str)
        except json.JSONDecodeError:
            video_bookmarks = []

        GLib.idle_add(self._on_wallpapers_loaded, static_paths, live_paths, video_bookmarks)

    def _on_wallpapers_loaded(self, static_paths, live_paths, video_bookmarks):
        """Updates the stores after wallpapers have been loaded."""
        self.texture_cache.clear()

        static_items = [WallpaperItem(p) for p in static_paths]
        self.static_store.splice(0, self.static_store.get_n_items(), static_items)
        print(f"Static store updated with {len(static_items)} items.")

        live_items = [WallpaperItem(p) for p in live_paths]
        url_items = [WallpaperItem(path=b.get('url'), title=b.get('title')) for b in video_bookmarks]
        self.live_store.splice(0, self.live_store.get_n_items(), live_items + url_items)
        print(f"Live store updated with {len(live_items) + len(url_items)} items.")

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
            if isinstance(item, OnlineWallpaperItem):
                if item.is_downloaded and item.local_path:
                    wallpaper_item = WallpaperItem(Path(item.local_path), title=item.title)
                    self._set_wallpaper(wallpaper_item)
            else:
                self._set_wallpaper(item)

    def _set_wallpaper(self, item):
        """Sets the given item as the wallpaper."""
        if not item:
            return
        
        path = item.path
        print(f"DEBUG: _set_wallpaper called for {path}")
        
        is_url = isinstance(path, str) and (path.startswith('http://') or path.startswith('https://'))
        
        # Display name: use title if available, otherwise use filename/URL
        display_name = item.title if item.title else (path if is_url else path.name)
        
        if is_url:
            # URL-based wallpaper
            self._set_url_wallpaper(path)
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper set to: {display_name}"))
        elif path.suffix.lower() in SUPPORTED_STATIC:
            # Static wallpaper
            self._set_static_wallpaper(path)
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper set to: {display_name}"))
        elif path.suffix.lower() in SUPPORTED_LIVE:
            # Live wallpaper
            self._set_live_wallpaper(path)
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Wallpaper set to: {display_name}"))

    def _set_static_wallpaper(self, path):
        """Sets a static wallpaper using the configured backend."""
        backend = self.settings.get_string('static-backend')
        
        if not backend:
            self.window.toast_overlay.add_toast(Adw.Toast.new("No static backend configured or installed."))
            return
        
        # Kill any running backend processes (e.g., mpvpaper for live wallpapers)
        kill_backend_processes()
        self.mpv_process = None
        
        name = path.name
        command = build_command(backend, path, self.settings)
        
        if not command:
            return
        
        try:
            subprocess.run(command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error setting wallpaper: {e}"))


    def _set_live_wallpaper(self, path):
        """Sets a live wallpaper using the configured backend."""
        backend = self.settings.get_string('live-backend')
        
        if not backend:
            self.window.toast_overlay.add_toast(Adw.Toast.new("No live backend configured or installed."))
            return
        
        if backend == 'swww' and path.suffix.lower() != '.gif':
            self.window.toast_overlay.add_toast(Adw.Toast.new("Swww backend only supports .gif for live wallpapers."))
            return
        
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

    def _set_url_wallpaper(self, url):
        """Sets a URL-based wallpaper (YouTube video) using mpvpaper."""
        backend = self.settings.get_string('live-backend')
        
        if backend != 'mpvpaper':
            self.window.toast_overlay.add_toast(Adw.Toast.new("URL wallpapers require mpvpaper backend."))
            return
        
        kill_backend_processes()
        self.mpv_process = None
        
        # Build command for URL playback
        cmd = build_command(backend, url, self.settings)
        
        if cmd:
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

    def _set_initial_mpv_state(self):
        """Sends initial volume and mute commands to a new mpvpaper instance."""
        self.send_mpv_command(["set_property", "volume", self.video_volume])
        self.send_mpv_command(["set_property", "mute", "no" if self.enable_video_sound else "yes"])
        return GLib.SOURCE_REMOVE

    def _on_random_button_clicked(self, button):
        """Sets a random wallpaper from the current view."""
        current_view = self.window.view_stack.get_visible_child_name()
        model = self.static_model.get_model() if current_view == 'static' else self.live_model.get_model()
        
        if model and model.get_n_items() > 0:
            random_pos = random.randint(0, model.get_n_items() - 1)
            self._set_wallpaper(model.get_item(random_pos))
        else:
            self.window.toast_overlay.add_toast(Adw.Toast.new("No wallpapers to choose from."))

    def _on_load_more_online_wallpapers_clicked(self, button):
        """Loads the next page of online wallpapers."""
        self.online_current_page += 1
        self._trigger_online_search(latest=False, page=self.online_current_page)

    def _on_list_item_right_clicked(self, gesture, n_press, x, y, list_item):
        """Handles right-click on a wallpaper list item."""
        item = list_item.get_item()
        if not item: return

        self.right_clicked_item = item
        menu = Gio.Menu()
        if isinstance(item.path, Path) and item.path.suffix.lower() in SUPPORTED_LIVE:
            # Only show recode option if video resolution exceeds display resolution
            show_recode = False
            try:
                monitor_width, monitor_height = get_monitor_resolution(self.window)
                if monitor_width and monitor_height:
                    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', str(item.path)]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    video_width, video_height = map(int, result.stdout.strip().split('x'))
                    if video_width > monitor_width or video_height > monitor_height:
                        show_recode = True
            except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as e:
                # If we can't determine resolution, show the option to be safe
                print(f"Could not determine video resolution for {item.path.name}: {e}")
                show_recode = True
            
            if show_recode:
                menu.append("Recode to display resolution", "app.recode_video")
        menu.append("Delete", "app.delete_wallpaper")
        menu.append("Properties", "app.show_properties")
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(list_item.get_child())
        popover.popup()

    def _on_online_list_item_right_clicked(self, gesture, n_press, x, y, list_item):
        """Handles right-click on an online wallpaper list item."""
        item = list_item.get_item()
        if not item: return

        self.right_clicked_item = item
        menu = Gio.Menu()
        menu.append("Download", "app.download_online_wallpaper")
        menu.append("Properties", "app.show_online_properties")
        if item.is_downloaded:
            menu.append("Delete", "app.delete_online_wallpaper")
        
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(list_item.get_child())
        popover.popup()

    def _on_download_online_wallpaper_activated(self, action, param):
        """Handles the 'Download' action from the online context menu."""
        if not self.right_clicked_item: return
        self._on_download_wallpaper_clicked(None, self.right_clicked_item)

    def _on_show_online_properties_activated(self, action, param):
        """Handles the 'Properties' action from the online context menu."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item

        # Wrap the image loading in a lambda to start the thread
        def load_image(item, picture):
            threading.Thread(target=self._load_full_online_image_thread, args=(item, picture), daemon=True).start()
        
        dialog = create_online_properties_dialog(
            self.window,
            item,
            load_image_callback=load_image
        )
        dialog.present(self.window)

    def _load_full_online_image_thread(self, item, picture_widget):
        """Loads the full online image in a background thread for the properties dialog."""
        try:
            print(f"Attempting to download full image from: {item.full_url}")
            response = requests.get(item.full_url)
            response.raise_for_status()
            print(f"Full image downloaded successfully for {item.wall_id}")
            
            bytes = GLib.Bytes.new(response.content)
            loader = GdkPixbuf.PixbufLoader.new()
            loader.write(bytes.get_data())
            loader.close()
            pixbuf = loader.get_pixbuf()
            print(f"Pixbuf created for full image {item.wall_id}")

            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            print(f"Texture created for full image {item.wall_id}")
            
            GLib.idle_add(picture_widget.set_paintable, texture)
            print(f"Set paintable for full image {item.wall_id}")

        except (requests.exceptions.RequestException, GLib.Error) as e:
            print(f"Error loading full image for {item.wall_id}: {e}")

    def _on_delete_online_wallpaper_activated(self, action, param):
        """Handles the 'Delete' action for a downloaded online wallpaper."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        
        if not item.is_downloaded or not item.local_path:
            self.window.toast_overlay.add_toast(Adw.Toast.new("This wallpaper hasn't been downloaded yet."))
            return
        
        dialog = create_confirmation_dialog(
            self.window,
            title=f"Delete '{item.wall_id}'?",
            body="This file will be permanently deleted. This action cannot be undone.",
            confirm_text="Delete",
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
            callback=self._on_delete_online_dialog_response,
            user_data=item
        )

        dialog.present(self.window)

    def _on_delete_online_dialog_response(self, dialog, response, item):
        """Handles the response from the delete confirmation dialog for online wallpapers."""
        if response == "confirm":  # Changed from "delete" to "confirm"
            if item.local_path and os.path.exists(item.local_path):
                try:
                    os.remove(item.local_path)
                    self.window.toast_overlay.add_toast(Adw.Toast.new(f"Deleted {item.wall_id}."))
                    item.is_downloaded = False
                    item.local_path = None
                    item.emit('download-status-changed', False, "")
                    self._load_wallpapers_async()
                except OSError as e:
                    self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error deleting file: {e}"))

    def _update_recode_ui(self):
        """Updates the spinner and popover based on the recode queue and download tasks."""
        with self.recode_lock:
            # Check if there are any active recode or download tasks
            is_active = bool(self.recode_currently_running or self.recode_queue)
            print(f"_update_recode_ui: is_active={is_active}")
            self.window.recode_revealer_container.set_visible(is_active)
            revealer = self.window.recode_revealer_container.get_first_child()
            if revealer:
                revealer.set_reveal_child(is_active)
            self.window.recode_spinner.spinning = is_active
            print(f"_update_recode_ui: recode_spinner.spinning={self.window.recode_spinner.spinning}")
            
            # Clear and repopulate the popover store
            self.recode_popover_store.remove_all()
            self.recode_popover_store.splice(0, 0, []) # Add this line to force a refresh
            if self.recode_currently_running:
                item = RecodeQueueItem(f"{self.recode_currently_running.path.name}", "Running", self.recode_currently_running)
                self.recode_popover_store.append(item)
            for item_in_queue in self.recode_queue:
                item = RecodeQueueItem(f"{item_in_queue.path.name}", "Queued", item_in_queue)
                self.recode_popover_store.append(item)

    def _update_download_ui(self):
        """Updates the spinner and popover based on the download tasks."""
        is_active = bool(self.download_popover_store.get_n_items() > 0)
        self.window.download_revealer_container.set_visible(is_active)
        revealer = self.window.download_revealer_container.get_first_child()
        if revealer:
            revealer.set_reveal_child(is_active)
        self.window.download_spinner.spinning = is_active

    def _on_stop_one_recode_clicked(self, button, item_to_stop):
        """Stops a single recode job from the queue or the running process."""
        with self.recode_lock:
            if self.recode_currently_running == item_to_stop:
                if self.recode_process:
                    try:
                        self.recode_process.terminate()
                        self.window.toast_overlay.add_toast(Adw.Toast.new(f"Stopping recode for: {item_to_stop.path.name}"))
                    except ProcessLookupError: pass 
                self.recode_currently_running = None
                GLib.idle_add(self._start_next_recode_if_possible)
            elif item_to_stop in self.recode_queue:
                self.recode_queue.remove(item_to_stop)
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Removed from queue: {item_to_stop.path.name}"))
        GLib.idle_add(self._update_recode_ui)

    def _on_stop_one_download_clicked(self, button, item_to_stop):
        """Stops a single download job from the queue."""
        # We don't have direct control over running download threads started by requests.get
        # So, we just remove the item from the UI.
        for i in range(self.download_popover_store.get_n_items()):
            if self.download_popover_store.get_item(i) == item_to_stop:
                self.download_popover_store.remove(i)
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Removed from downloads: {item_to_stop.text}"))
                break
        GLib.idle_add(self._update_download_ui)

    def _on_stop_all_recodes_clicked(self, button):
        """Stops the running recode process and clears the queue."""
        with self.recode_lock:
            self.recode_queue.clear()
            if self.recode_currently_running:
                if self.recode_process:
                    try: self.recode_process.terminate()
                    except ProcessLookupError: pass
                self.recode_currently_running = None
        self.window.toast_overlay.add_toast(Adw.Toast.new("All recode jobs stopped."))
        self.window.recode_button.get_popover().popdown()
        GLib.idle_add(self._update_recode_ui)

    def _on_stop_all_downloads_clicked(self, button):
        """Stops all active downloads and clears the download queue."""
        # We don't have direct control over running download threads started by requests.get
        # For now, just clear the queue
        self.download_popover_store.remove_all() # This will clear the displayed items
        # We don't have direct control over running download threads started by requests.get
        # So, we just clear the UI and let the threads finish in the background.
        self.window.toast_overlay.add_toast(Adw.Toast.new("All download jobs stopped."))
        self.window.download_button.get_popover().popdown()
        GLib.idle_add(self._update_download_ui)
    
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
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"'{item.path.name}' is already in the queue."))
                return
            self.recode_queue.append(item)
        self.window.toast_overlay.add_toast(Adw.Toast.new(f"Added '{item.path.name}' to the recode queue."))
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
                self.window.toast_overlay.add_toast(Adw.Toast.new(toast_message))
                GLib.idle_add(self._load_wallpapers_async)
            else:
                if "terminated" not in (error_message or "").lower():
                    toast_message = f"Failed to recode '{item.path.name}'."
                    print(f"recoding failed for {item.path.name}: {error_message}")
                    self.window.toast_overlay.add_toast(Adw.Toast.new(toast_message))
        self._update_recode_ui()
        self._start_next_recode_if_possible()
        return False

    def _on_delete_wallpaper_activated(self, action, param):
        """Handles the 'Delete' action from the context menu."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        name = item.path if isinstance(item.path, str) else item.path.name
        
        dialog = create_confirmation_dialog(
            self.window,
            title=f"Delete '{name}'?",
            body="This file will be permanently deleted. This action cannot be undone.",
            confirm_text="Delete",
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
            callback=self._on_delete_dialog_response,
            user_data=item
        )
        dialog.present(self.window)


    def _on_delete_dialog_response(self, dialog, response, item):
        """Handles the response from the delete confirmation dialog."""
        if response != "confirm":  # Changed from "delete" to "confirm"
            return

        is_url = isinstance(item.path, str)
        name = item.title or (item.path if is_url else item.path.name)

        # Remove from the appropriate store
        target_store = None
        if isinstance(item.path, Path) and item.path.suffix.lower() in SUPPORTED_STATIC:
            target_store = self.static_store
        elif isinstance(item.path, Path) and item.path.suffix.lower() in SUPPORTED_LIVE:
            target_store = self.live_store
        elif is_url: # URL-based live wallpaper
            target_store = self.live_store

        if target_store:
            for i in range(target_store.get_n_items()):
                if target_store.get_item(i) == item:
                    target_store.remove(i)
                    break
        
        if is_url:
            try:
                bookmarks_str = self.settings.get_string('video-bookmarks')
                bookmarks = json.loads(bookmarks_str)
            except (json.JSONDecodeError, TypeError):
                bookmarks = []
            
            bookmarks = [b for b in bookmarks if b.get('url') != item.path]
            self.settings.set_string('video-bookmarks', json.dumps(bookmarks))
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"'{name}' removed."))
        else:
            try:
                item.path.unlink()
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"'{name}' deleted."))
            except OSError as e:
                self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error deleting file: {e}"))

    def _format_size(self, size_bytes):
        """Formats a file size in bytes to a human-readable string."""
        if size_bytes == 0: return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    

    def _populate_media_properties(self, group, item):
        """[Main Thread] Runs ffprobe and adds media properties to the given preferences group."""
        name = item.title or (item.path if isinstance(item.path, str) else item.path.name)
        
        def add_property_row(title, subtitle):
            row = Adw.ActionRow(title=title)
            row.set_subtitle(str(subtitle))
            group.add(row)

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
                    num, den = stream['r_frame_rate'].split('/')
                    if int(den) != 0:
                        add_property_row("Frame Rate", f"{round(int(num)/int(den), 2)} fps")
                if 'bit_rate' in stream and stream.get('bit_rate') is not None:
                        add_property_row("Bit Rate", f"{self._format_size(int(stream['bit_rate']))}/s")
                elif 'bit_rate' in media_info.get('format', {}) and media_info.get('format', {}).get('bit_rate') is not None:
                        add_property_row("Bit Rate", f"{self._format_size(int(media_info['format']['bit_rate']))}/s")
        except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            print(f"Could not get media properties for {name}: {e}")

    def _load_static_preview(self, item, picture):
        """Loads a preview image for static wallpaper properties dialog."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(item.path),
                width=800,
                height=600,
                preserve_aspect_ratio=True
            )
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            picture.set_paintable(texture)
        except Exception as e:
            print(f"Could not load preview for {item.path.name}: {e}")

    def _on_delete_static_wallpaper(self, button, item):
        """Handles delete button click from static properties dialog."""
        try:
            item.path.unlink()
            # Remove from store
            target_store = None
            if item.path.suffix.lower() in SUPPORTED_STATIC:
                target_store = self.static_store
            elif item.path.suffix.lower() in SUPPORTED_LIVE:
                target_store = self.live_store
            
            if target_store:
                for i in range(target_store.get_n_items()):
                    if target_store.get_item(i) == item:
                        target_store.remove(i)
                        break
            
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Deleted {item.path.name}"))
        except Exception as e:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Error deleting file: {e}"))

    def _on_show_properties_activated(self, action, param):
        """Handles the 'Properties' action from the context menu by showing a dialog."""
        if not self.right_clicked_item: return
        item = self.right_clicked_item
        is_url = isinstance(item.path, str)
        
        try:
            dialog = create_properties_dialog(
                self.window,
                item,
                is_url,
                on_title_change=self._update_url_title,
                populate_media_callback=self._populate_media_properties,
                format_size_callback=self._format_size,
                load_preview_callback=self._load_static_preview if not is_url else None,
                on_delete_callback=self._on_delete_static_wallpaper if not is_url else None
            )
            dialog.present(self.window)
        except FileNotFoundError:
            self.window.toast_overlay.add_toast(Adw.Toast.new("File not found."))


    def _wallpaper_filter_func(self, item):
        """Filter function for static wallpapers."""
        if not self.search_text: return True
        return self.search_text.lower() in item.path.name.lower()

    def _live_wallpaper_filter_func(self, item):
        """Filter function for live wallpapers."""
        is_url = isinstance(item.path, str)
        name = item.title or (item.path if is_url else item.path.name)

        if not is_url:
            backend = self.settings.get_string('live-backend')
            if backend == 'swww' and item.path.suffix.lower() != '.gif':
                return False
            if self.hide_original_after_recode and '_recoded' not in item.path.name:
                recoded_path = item.path.parent / 'recoded' / f"{item.path.stem}_recoded{item.path.suffix}"
                if recoded_path.exists():
                    return False

        if self.search_text and self.search_text.lower() not in name.lower():
            return False
            
        return True

    def _online_wallpaper_filter_func(self, item):
        """Filter function for online wallpapers."""
        if not self.online_search_text: return True
        # This is a placeholder. We will filter by tags or other metadata later.
        return self.online_search_text.lower() in item.wall_id.lower()

    def _on_search_changed(self, search_entry):
        """Handles changes in the search entry text."""
        current_view = self.window.view_stack.get_visible_child_name()
        if current_view == 'online':
            self.online_search_text = search_entry.get_text()
            # self.online_filter.changed(Gtk.FilterChange.DIFFERENT)
        else:
            self.search_text = search_entry.get_text()
            self.static_filter.changed(Gtk.FilterChange.DIFFERENT)
            self.live_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_status_page_visibility()
        self._update_random_button_visibility()

    def _on_search_activated(self, search_entry):
        """Handles when the user presses Enter in the search entry."""
        current_view = self.window.view_stack.get_visible_child_name()
        print(f"_on_search_activated called. Current view: {current_view}")
        if current_view == 'online':
            self._trigger_online_search()

    def _on_purity_toggled(self, switch, name):
        """Handles toggling of the purity switches."""
        # If a button is deactivated, and it's the last one, reactivate it.
        if not switch.get_active():
            # The state is already changed when the signal is emitted.
            # So we check if ANY button is active. If not, the one that was just
            # toggled was the last one.
            if not self.window.sfw_switch.get_active() and \
               not self.window.sketchy_switch.get_active() and \
               not self.window.nsfw_switch.get_active():
                switch.set_active(True)
                return # Don't continue, as this would be a false state change.

        is_active = switch.get_active()
        if name == "sfw":
            self.settings.set_boolean('wallhaven-purity-sfw', is_active)
        elif name == "sketchy":
            self.settings.set_boolean('wallhaven-purity-sketchy', is_active)
        elif name == "nsfw":
            self.settings.set_boolean('wallhaven-purity-nsfw', is_active)

        if self.window.view_stack.get_visible_child_name() == 'online' and self.online_search_text:
            self._trigger_online_search()

    def _on_category_toggled(self, switch, name):
        """Handles toggling of the category switches."""
        if not switch.get_active():
            if not self.window.general_switch.get_active() and \
               not self.window.anime_switch.get_active() and \
               not self.window.people_switch.get_active():
                switch.set_active(True)
                return

        is_active = switch.get_active()
        if name == "general":
            self.settings.set_boolean('wallhaven-category-general', is_active)
        elif name == "anime":
            self.settings.set_boolean('wallhaven-category-anime', is_active)
        elif name == "people":
            self.settings.set_boolean('wallhaven-category-people', is_active)

        if self.window.view_stack.get_visible_child_name() == 'online':
            self._trigger_online_search()

    def _on_resolution_changed(self, entry_row):
        """Handles changes in the resolution entry."""
        resolution_text = entry_row.get_text().strip()
        self.settings.set_string('wallhaven-resolution', resolution_text)
        self.online_resolution_text = resolution_text # Update internal state
        if self.window.view_stack.get_visible_child_name() == 'online':
            self._trigger_online_search()

    def _on_atleast_changed(self, entry_row):
        """Handles changes in the minimum resolution entry."""
        atleast_text = entry_row.get_text().strip()
        self.settings.set_string('wallhaven-atleast', atleast_text)
        self.online_atleast_text = atleast_text # Update internal state
        if self.window.view_stack.get_visible_child_name() == 'online':
            self._trigger_online_search()

    def _on_ratio_changed(self, entry_row):
        """Handles changes in the aspect ratio entry."""
        ratio_text = entry_row.get_text().strip()
        self.settings.set_string('wallhaven-ratios', ratio_text)
        self.online_ratio_text = ratio_text # Update internal state
        if self.window.view_stack.get_visible_child_name() == 'online':
            self._trigger_online_search()

    def _trigger_online_search(self, latest=False, page=1):
        """Triggers a search for online wallpapers."""
        print("Triggering online search...")
        if latest:
            self.online_current_page = 1
        else:
            self.online_current_page = page

        query = self.online_search_text
        api_key = self.settings.get_string('wallhaven-api-key')
        resolution = self.settings.get_string('wallhaven-resolution')
        atleast = self.settings.get_string('wallhaven-atleast')
        ratios = self.settings.get_string('wallhaven-ratios')

        sfw = self.window.sfw_switch.get_active()
        sketchy = self.window.sketchy_switch.get_active()
        nsfw = self.window.nsfw_switch.get_active()
        general = self.window.general_switch.get_active()
        anime = self.window.anime_switch.get_active()
        people = self.window.people_switch.get_active()
        
        if not api_key:
            self.window.toast_overlay.add_toast(Adw.Toast.new("Wallhaven API key not set in preferences."))
            return

        self.background_tasks += 1
        self._update_spinner()
        threading.Thread(target=self._online_search_thread, args=(query, api_key, sfw, sketchy, nsfw, general, anime, people, resolution, atleast, ratios, self.online_current_page), daemon=True).start()

    def _online_search_thread(self, query, api_key, sfw, sketchy, nsfw, general, anime, people, resolution, atleast, ratios, page):
        """Runs the online search in a background thread."""
        results = search_wallhaven(query, api_key, sfw, sketchy, nsfw, general, anime, people, resolution, atleast, ratios, page)
        GLib.idle_add(self._on_online_search_finished, results)

    def _on_online_search_finished(self, results):
        """Updates the online store after the search is finished."""
        self.background_tasks -= 1
        self._update_spinner()

        if "error" in results:
            self.window.toast_overlay.add_toast(Adw.Toast.new(f"Online search error: {results['error']}"))
            return

        print(f"Processed online search results: {results}")
        
        if self.online_current_page == 1:
            self.online_store.splice(0, self.online_store.get_n_items(), []) # Clear existing items
            for item in results:
                self.online_store.append(item)
        else:
            for item in results:
                self.online_store.append(item)
        
        # self.online_filter.changed(Gtk.FilterChange.DIFFERENT) # Reverted to this
        self._update_status_page_visibility()

    def _update_status_page_visibility(self):
        """Shows or hides the 'No Results' page."""
        is_searching = bool(self.search_text) or bool(self.online_search_text)
        current_view = self.window.view_stack.get_visible_child_name()
        
        if current_view in ['static', 'live', 'online']:
            if current_view == 'static':
                model = self.window.static_view.get_model()
            elif current_view == 'live':
                model = self.window.live_view.get_model()
            else: # online
                model = self.window.online_view.get_model()

            show_status = is_searching and model and model.get_n_items() == 0
            self.window.status_page.set_visible(show_status)
        else:
            self.window.status_page.set_visible(False)

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
        dialog = create_confirmation_dialog(
            self.window,
            title="Clear Cache?",
            body="All cached thumbnails will be deleted. This action cannot be undone.",
            confirm_text="Clear",
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
            callback=self._on_clear_cache_dialog_response
        )
        dialog.present(self.window)

    def _on_clear_cache_dialog_response(self, dialog, response):
        if response == "confirm":  # Changed from "clear" to "confirm"

            for f in self.cache_dir.glob('*'):
                try:
                    f.unlink()
                except OSError as e:
                    print(f"Error deleting cache file {f}: {e}")
            
            self.texture_cache.clear()
            self.window.toast_overlay.add_toast(Adw.Toast.new("Thumbnail cache cleared"))

            # Force a re-bind of all items in both views to trigger thumbnail regeneration
            for store in [self.static_store, self.live_store]:
                items = [store.get_item(i) for i in range(store.get_n_items())]
                new_items = [WallpaperItem(path=item.path, title=item.title) for item in items]
                store.splice(0, store.get_n_items(), new_items)

    def _on_reload_css_clicked(self, button):
        """Reloads the custom CSS."""
        self._update_css()
        self.window.toast_overlay.add_toast(Adw.Toast.new("CSS reloaded"))

    def _on_corner_radius_changed(self, adjustment):
        """Handles changes to the corner radius setting."""
        self.corner_radius = int(adjustment.get_value())
        self.settings.set_int('corner-radius', self.corner_radius)
        self._update_corner_radius_css()

    def _on_preview_adjustment_changed(self, adjustment):
        """Handles changes to the preview size setting."""
        self.preview_size = int(adjustment.get_value())
        self.settings.set_int('preview-size', self.preview_size)
        self._emit_preview_size_changed()

    def _emit_preview_size_changed(self):
        """Forces a re-bind of all wallpaper items to update their display."""
        print(f"  _emit_preview_size_changed: Forcing re-bind for stores.")
        for store in [self.static_store, self.live_store, self.online_store]:
            # Create a new list of items to trigger a re-bind
            current_items = [store.get_item(i) for i in range(store.get_n_items())]
            # Splice with the same items to force the ListView to re-evaluate them
            store.splice(0, store.get_n_items(), current_items)

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
        self.window.toast_overlay.add_toast(Adw.Toast.new("mpv socket path updated. Restart live wallpaper to apply."))

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

    def _on_mpvpaper_fill_type_changed(self, combo, _):
        """Handles changes to the mpvpaper fill type."""
        model = combo.get_model()
        self.mpvpaper_fill_type = model.get_string(combo.get_selected())
        self.settings.set_string('mpvpaper-fill-type', self.mpvpaper_fill_type)

    def _on_swww_fps_changed(self, adjustment):
        """Handles changes to the swww transition fps."""
        self.swww_transition_fps = int(adjustment.get_value())
        self.settings.set_int('swww-transition-fps', self.swww_transition_fps)

    def _on_recode_all_clicked(self, button):
        """Shows a confirmation dialog before starting a batch recode."""
        dialog = create_confirmation_dialog(
            self.window,
            title="Recode all videos?",
            body="This will recode all videos with a resolution higher than your display. This may take a long time and consume significant CPU resources. Original files will not be modified.",
            confirm_text="Recode All",
            confirm_appearance=Adw.ResponseAppearance.SUGGESTED,
            callback=self._on_recode_all_dialog_response
        )
        dialog.present(self.window)


    def _on_recode_all_dialog_response(self, dialog, response):
        """Handles the response from the batch recode confirmation dialog."""
        if response == "confirm":  # Changed from "recode" to "confirm"

            self.window.toast_overlay.add_toast(Adw.Toast.new("Starting batch recode..."))
            thread = threading.Thread(target=self._recode_all_thread, args=(self.window,), daemon=True)
            thread.start()

    def _recode_all_thread(self, window):
        """Identifies and adds high-resolution videos to the queue."""
        monitor_width, monitor_height = get_monitor_resolution(window)
        if not monitor_width or not monitor_height:
            GLib.idle_add(self.window.toast_overlay.add_toast, Adw.Toast.new("Error: Could not determine display resolution for batch recode."))
            return
        items_to_process = [self.live_store.get_item(i) for i in range(self.live_store.get_n_items())]
        queued_count = 0
        for item in items_to_process:
            if isinstance(item.path, str): # Skip URLs
                continue
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
            GLib.idle_add(self.window.toast_overlay.add_toast, Adw.Toast.new(f"Added {queued_count} videos to the recode queue."))
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
