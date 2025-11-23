"""
Reusable dialog creation functions for the Manpaper application.

This module provides factory functions for creating common dialogs used throughout
the application, promoting code reuse and consistency.
"""

import datetime
from pathlib import Path
from gi.repository import Gtk, Adw, GLib
from ..config import SUPPORTED_STATIC, SUPPORTED_LIVE
from ..utils import get_monitor_resolution


def create_confirmation_dialog(window, title, body, confirm_text="Confirm",
                               confirm_appearance=Adw.ResponseAppearance.SUGGESTED,
                               callback=None, user_data=None):
    """
    Creates a generic confirmation dialog with cancel/confirm responses.
    
    Args:
        window: Parent window for the dialog
        title: Dialog title text
        body: Dialog body/message text
        confirm_text: Text for the confirm button (default: "Confirm")
        confirm_appearance: Appearance of confirm button (default: SUGGESTED)
        callback: Function to call on response (receives dialog, response_id, user_data)
        user_data: Optional data to pass to callback
        
    Returns:
        Adw.AlertDialog configured with the specified parameters
    """
    dialog = Adw.AlertDialog.new(title)
    dialog.set_body(body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", confirm_text)
    dialog.set_response_appearance("confirm", confirm_appearance)
    dialog.set_default_response("cancel")
    
    if callback:
        if user_data is not None:
            dialog.connect("response", callback, user_data)
        else:
            dialog.connect("response", callback)
    
    return dialog


def create_url_input_dialog(window, callback):
    """
    Creates a dialog for entering a YouTube video URL.
    
    Args:
        window: Parent window for the dialog
        callback: Function to call on response (receives dialog, response_id)
        
    Returns:
        Adw.Dialog configured for YouTube URL input
    """
    dialog = Adw.Dialog()
    dialog.set_title("Add YouTube Video")
    
    # Create toolbar view with header
    toolbar_view = Adw.ToolbarView()
    header_bar = Adw.HeaderBar()
    toolbar_view.add_top_bar(header_bar)
    
    # Create content area
    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content_box.set_margin_top(24)
    content_box.set_margin_bottom(24)
    content_box.set_margin_start(24)
    content_box.set_margin_end(24)
    
    # Add URL entry row
    url_entry = Adw.EntryRow(title="YouTube URL")
    url_entry.set_text("")
    url_entry.set_show_apply_button(False)
    content_box.append(url_entry)
    
    # Add button box
    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    button_box.set_halign(Gtk.Align.END)
    button_box.set_margin_top(12)
    
    cancel_button = Gtk.Button(label="Cancel")
    cancel_button.add_css_class("pill")
    
    # Add button for streaming (original behavior)
    add_button = Gtk.Button(label="Add")
    add_button.add_css_class("pill")
    add_button.add_css_class("suggested-action")
    
    # Download button for downloading the video
    download_button = Gtk.Button(label="Download")
    download_button.add_css_class("pill")
    
    button_box.append(cancel_button)
    button_box.append(download_button)
    button_box.append(add_button)
    content_box.append(button_box)
    
    toolbar_view.set_content(content_box)
    dialog.set_child(toolbar_view)
    
    # Connect button signals
    def on_cancel_clicked(button):
        callback(dialog, "cancel")
        dialog.close()
    
    def on_add_clicked(button):
        callback(dialog, "add")
        dialog.close()
    
    def on_download_clicked(button):
        callback(dialog, "download")
        dialog.close()
    
    cancel_button.connect("clicked", on_cancel_clicked)
    add_button.connect("clicked", on_add_clicked)
    download_button.connect("clicked", on_download_clicked)
    
    # Store reference to entry for callback to access
    dialog.url_entry = url_entry
    
    return dialog



def create_properties_dialog(window, item, is_url, on_title_change=None,
                             populate_media_callback=None, format_size_callback=None,
                             load_preview_callback=None, on_delete_callback=None):
    """
    Creates a properties dialog for wallpaper items.
    
    Args:
        window: Parent window for the dialog
        item: WallpaperItem to show properties for
        is_url: Whether the item is a URL-based wallpaper
        on_title_change: Callback for when URL title changes (receives item, new_title)
        populate_media_callback: Callback to populate media properties (receives group, item)
        format_size_callback: Callback to format file sizes (receives size_bytes)
        load_preview_callback: Callback to load preview image (receives item, picture)
        on_delete_callback: Callback for delete button (receives button, item)
        
    Returns:
        Adw.Dialog configured with item properties
    """
    desired_width = 400 # Default
    preview_height = 300
    
    try:
        if item.resolution:
            w, h = map(int, item.resolution.split('x'))
            aspect = w / h
            
            if aspect < 1: # Portrait
                preview_height = 500
                desired_width = int(preview_height * aspect)
                # Clamp width to reasonable bounds for portrait (narrower min)
                desired_width = max(340, min(desired_width, 800))
            else: # Landscape
                preview_height = 300
                desired_width = int(preview_height * aspect)
                # Clamp width to reasonable bounds for landscape
                desired_width = max(380, min(desired_width, 800))
                
    except Exception:
        pass
    
    # Clamp to parent window width to avoid exceeding available space
    window_width = window.get_width()
    if window_width > 0:
        # Leave generous margin for padding, margins, and floating sheet chrome
        max_dialog_width = window_width - 120
        desired_width = min(desired_width, max_dialog_width)

    dialog = Adw.Dialog()
    dialog.set_title("Properties")
    dialog.set_content_width(desired_width)

    toolbar_view = Adw.ToolbarView()
    header_bar = Adw.HeaderBar()
    toolbar_view.add_top_bar(header_bar)
    
    page = Adw.PreferencesPage()
    toolbar_view.set_content(page)
    dialog.set_child(toolbar_view)

    # Add preview image/video if callback provided and not a URL
    if load_preview_callback and not is_url:
        preview_group = Adw.PreferencesGroup()
        page.add(preview_group)
        
        # Check if it's a video file
        is_video = item.path.suffix.lower() in SUPPORTED_LIVE
        
        if is_video:
            # Get display resolution to match aspect ratio
            monitor_width, monitor_height = get_monitor_resolution(window)
            if not monitor_width or not monitor_height:
                # Fallback to 16:9 if we can't get monitor resolution
                monitor_width, monitor_height = 1920, 1080
            
            display_aspect = monitor_width / monitor_height
            
            # Set video dimensions to match display aspect ratio
            # Use a reasonable preview height and calculate width from aspect ratio
            preview_height = 280
            preview_width = int(preview_height * display_aspect)
            
            # Use Gtk.Video for video files
            video = Gtk.Video()
            video.set_autoplay(True)
            video.set_loop(True)
            # Set fixed size matching display aspect ratio
            video.set_size_request(preview_width, preview_height)
            video.set_halign(Gtk.Align.CENTER)
            video.set_valign(Gtk.Align.CENTER)
            
            # Create media file from path
            media_file = Gtk.MediaFile.new_for_filename(str(item.path))
            media_file.set_muted(True)  # Mute the video by default
            video.set_media_stream(media_file)
            
            # Wrap in AspectFrame to force cropping
            aspect_frame = Gtk.AspectFrame()
            aspect_frame.set_ratio(display_aspect)
            aspect_frame.set_obey_child(True)  # Don't obey video's aspect ratio
            aspect_frame.set_child(video)
            
            video_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            video_box.append(aspect_frame)
            video_box.set_margin_top(12)
            video_box.set_margin_bottom(12)
            video_box.set_margin_start(12)
            video_box.set_margin_end(12)
            preview_group.add(video_box)
        else:
            # Use Gtk.Picture for image files
            picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN)
            picture.set_size_request(desired_width, preview_height)
            picture.set_halign(Gtk.Align.CENTER)
            picture.set_valign(Gtk.Align.CENTER)
            
            picture_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            picture_box.append(picture)
            picture_box.set_margin_top(12)
            picture_box.set_margin_bottom(12)
            picture_box.set_margin_start(12)
            picture_box.set_margin_end(12)
            picture_box.set_hexpand(True)
            picture.set_hexpand(True)
            preview_group.add(picture_box)
            
            # Load preview
            load_preview_callback(item, picture)

    group = Adw.PreferencesGroup()
    page.add(group)

    def add_property_row(title, subtitle):
        row = Adw.ActionRow(title=title)
        row.set_subtitle(str(subtitle))
        group.add(row)
    
    if is_url:
        # Create title entry with built-in apply button
        title_entry = Adw.EntryRow(title="Title")
        title_entry.set_text(item.title or "")
        title_entry.set_show_apply_button(True)  # Show apply button when editing
        
        def on_title_apply(entry):
            if on_title_change:
                new_title = entry.get_text().strip()
                print(f"DEBUG Apply: title_entry.get_text()='{new_title}', item.title='{item.title}'")
                if new_title and new_title != item.title:
                    print(f"DEBUG: Calling on_title_change with new_title='{new_title}'")
                    on_title_change(item, new_title)
        
        title_entry.connect("apply", on_title_apply)
        group.add(title_entry)
        
        add_property_row("Type", "Video URL")
        
        # Create URL row with copy button
        url_row = Adw.ActionRow(title="URL")
        url_row.set_subtitle(str(item.path))
        url_row.set_subtitle_lines(2)
        
        # Add copy button
        copy_button = Gtk.Button()
        copy_button.set_icon_name("edit-copy-symbolic")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.add_css_class("flat")
        copy_button.set_tooltip_text("Copy URL to clipboard")
        
        def on_copy_clicked(btn):
            clipboard = window.get_clipboard()
            clipboard.set(item.path)
            # Show a brief toast notification
            if hasattr(window, 'toast_overlay'):
                toast = Adw.Toast.new("URL copied to clipboard")
                toast.set_timeout(2)
                window.toast_overlay.add_toast(toast)
        
        copy_button.connect("clicked", on_copy_clicked)
        url_row.add_suffix(copy_button)
        group.add(url_row)
    else:
        try:
            stat_info = item.path.stat()
            add_property_row("Type", item.path.suffix.upper()[1:] + " File")
            add_property_row("Path", str(item.path.parent))
            
            if format_size_callback:
                add_property_row("Size", format_size_callback(stat_info.st_size))
            else:
                add_property_row("Size", f"{stat_info.st_size} bytes")
                
            add_property_row("Last Modified", 
                           datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S'))
        except FileNotFoundError:
            # Let the caller handle the error toast
            pass

    is_static = not is_url and item.path.suffix.lower() in SUPPORTED_STATIC
    if not is_static and not is_url and populate_media_callback:
        populate_media_callback(group, item)
    
    # Add delete button in bottom bar if callback provided and not a URL
    if on_delete_callback and not is_url:
        delete_button = Gtk.Button(label="Delete Wallpaper")
        delete_button.add_css_class("destructive-action")
        delete_button.add_css_class("pill")
        delete_button.set_hexpand(True)
        
        def on_delete_clicked(btn):
            def on_confirm(confirm_dlg, response):
                if response == "confirm":
                    on_delete_callback(btn, item)
                    dialog.force_close()
            
            confirm_dialog = create_confirmation_dialog(
                window,
                "Delete Wallpaper?",
                f"Are you sure you want to delete '{item.path.name}'? This cannot be undone.",
                confirm_text="Delete",
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
                callback=on_confirm
            )
            confirm_dialog.present(window)
        
        delete_button.connect("clicked", on_delete_clicked)
        
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bottom_bar.add_css_class("toolbar")
        bottom_bar.set_margin_top(6)
        bottom_bar.set_margin_bottom(6)
        bottom_bar.set_margin_start(6)
        bottom_bar.set_margin_end(6)
        bottom_bar.append(delete_button)
        
        toolbar_view.add_bottom_bar(bottom_bar)
        
    return dialog


def create_online_properties_dialog(window, item, load_image_callback=None):
    """
    Creates a properties dialog for online wallpaper items.
    
    Args:
        window: Parent window for the dialog
        item: OnlineWallpaperItem to show properties for
        load_image_callback: Callback to load the full image (receives item, picture)
        
    Returns:
        Adw.Dialog configured with online item properties
    """
    dialog = Adw.Dialog()
    dialog.set_title("Properties")

    # Calculate desired width and height based on aspect ratio
    desired_width = 400 # Default
    preview_height = 300
    
    try:
        if item.resolution:
            w, h = map(int, item.resolution.split('x'))
            aspect = w / h
            
            if aspect < 1: # Portrait
                preview_height = 500
                desired_width = int(preview_height * aspect)
                # Clamp width to reasonable bounds for portrait (narrower min)
                desired_width = max(340, min(desired_width, 800))
            else: # Landscape
                preview_height = 300
                desired_width = int(preview_height * aspect)
                # Clamp width to reasonable bounds for landscape
                desired_width = max(380, min(desired_width, 800))
                
    except Exception:
        pass
    
    # Clamp to parent window width to avoid exceeding available space
    window_width = window.get_width()
    if window_width > 0:
        # Leave generous margin for padding, margins, and floating sheet chrome
        max_dialog_width = window_width - 120
        desired_width = min(desired_width, max_dialog_width)
        
    dialog.set_content_width(desired_width)

    toolbar_view = Adw.ToolbarView()
    header_bar = Adw.HeaderBar()
    toolbar_view.add_top_bar(header_bar)
    
    page = Adw.PreferencesPage()
    toolbar_view.set_content(page)
    dialog.set_child(toolbar_view)

    # Image preview group (at the top)
    image_group = Adw.PreferencesGroup()
    page.add(image_group)
    
    picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN)
    # Allow the picture to expand, but set a reasonable minimum height
    picture.set_size_request(desired_width, preview_height)
    picture.set_halign(Gtk.Align.CENTER)
    picture.set_valign(Gtk.Align.CENTER)
    
    picture_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    picture_box.append(picture)
    picture_box.set_margin_top(12)
    picture_box.set_margin_bottom(12)
    picture_box.set_margin_start(12)
    picture_box.set_margin_end(12)
    # Ensure the box and picture can expand
    picture_box.set_hexpand(True)
    picture.set_hexpand(True)
    image_group.add(picture_box)
    
    # Load image if callback provided
    if load_image_callback:
        load_image_callback(item, picture)

    # Properties group
    props_group = Adw.PreferencesGroup()
    page.add(props_group)

    def add_property_row(title, subtitle):
        row = Adw.ActionRow(title=title)
        row.set_subtitle(str(subtitle))
        props_group.add(row)

    add_property_row("ID", item.wall_id)
    add_property_row("Resolution", item.resolution)
    add_property_row("Purity", item.purity)
    
    # URL row with copy button
    url_row = Adw.ActionRow(title="URL")
    url_row.set_subtitle(str(item.full_url))
    url_row.set_subtitle_lines(2)
    
    copy_button = Gtk.Button()
    copy_button.set_icon_name("edit-copy-symbolic")
    copy_button.set_valign(Gtk.Align.CENTER)
    copy_button.add_css_class("flat")
    copy_button.set_tooltip_text("Copy URL to clipboard")
    
    def on_copy_clicked(btn):
        clipboard = window.get_clipboard()
        clipboard.set(item.full_url)
        if hasattr(window, 'toast_overlay'):
            toast = Adw.Toast.new("URL copied to clipboard")
            toast.set_timeout(2)
            window.toast_overlay.add_toast(toast)
    
    copy_button.connect("clicked", on_copy_clicked)
    url_row.add_suffix(copy_button)
    props_group.add(url_row)

    file_type = Path(item.full_url).suffix.lstrip('.')
    if file_type:
        add_property_row("File Type", file_type.upper())
    
    # Download/Delete button in bottom bar
    if item.is_downloaded:
        action_button = Gtk.Button(label="Delete Wallpaper")
        action_button.add_css_class("destructive-action")
        
        def on_action_clicked(btn):
            def on_confirm(confirm_dlg, response):
                if response == "confirm":
                    # Access the app through the window to trigger delete
                    if hasattr(window, 'app'):
                        window.app._on_delete_wallpaper_clicked(btn, item)
                    # Close the properties dialog
                    dialog.force_close()
            
            confirm_dialog = create_confirmation_dialog(
                window,
                "Delete Wallpaper?",
                f"Are you sure you want to delete '{item.wall_id}'? This cannot be undone.",
                confirm_text="Delete",
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
                callback=on_confirm
            )
            confirm_dialog.present(window)

    else:
        action_button = Gtk.Button(label="Download Wallpaper")
        action_button.add_css_class("suggested-action")
        
        def on_action_clicked(btn):
            # Access the app through the window to trigger download
            if hasattr(window, 'app'):
                window.app._on_download_wallpaper_clicked(btn, item)
            dialog.force_close()

    action_button.add_css_class("pill")
    action_button.set_hexpand(True)
    action_button.connect("clicked", on_action_clicked)
    
    bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    bottom_bar.add_css_class("toolbar")
    bottom_bar.set_margin_top(6)
    bottom_bar.set_margin_bottom(6)
    bottom_bar.set_margin_start(6)
    bottom_bar.set_margin_end(6)
    bottom_bar.append(action_button)
    
    toolbar_view.add_bottom_bar(bottom_bar)

    return dialog


def create_about_dialog(window):
    """
    Creates and returns the application About dialog.
    
    Args:
        window: Parent window for the dialog
        
    Returns:
        Adw.AboutDialog with application information
    """
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
    return dialog


def create_shortcuts_window(window):
    """
    Creates and returns the keyboard shortcuts window.
    
    Args:
        window: Parent window for the shortcuts window
        
    Returns:
        Gtk.ShortcutsWindow with all application shortcuts
    """
    shortcuts_window = Gtk.ShortcutsWindow(transient_for=window)
    section = Gtk.ShortcutsSection()
    
    def add_shortcut(group, title, accelerator):
        group.append(Gtk.ShortcutsShortcut(title=title, accelerator=accelerator))

    general_group = Gtk.ShortcutsGroup(title="General")
    add_shortcut(general_group, "Toggle Search Bar", "<Control>F")
    section.append(general_group)

    nav_group = Gtk.ShortcutsGroup(title="Navigation")
    add_shortcut(nav_group, "Go to Static Wallpapers", "<Alt>1")
    add_shortcut(nav_group, "Go to Live Wallpapers", "<Alt>2")
    add_shortcut(nav_group, "Go to Online Wallpapers", "<Alt>3")
    add_shortcut(nav_group, "Go to Preferences", "<Alt>4")
    section.append(nav_group)

    view_group = Gtk.ShortcutsGroup(title="View")
    add_shortcut(view_group, "Preview Zoom In", "<Ctrl>ScrollUp")
    add_shortcut(view_group, "Preview Zoom Out", "<Ctrl>ScrollDown")
    section.append(view_group)

    shortcuts_window.set_child(section)
    return shortcuts_window
