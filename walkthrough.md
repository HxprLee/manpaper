# Properties Dialog UI Fixes, Bug Fix & Delete Button

## Overview
We addressed the layout issues in the "Properties" dialog, specifically for online wallpapers. The "Download Wallpaper" button was floating awkwardly, and the URL text could potentially break the layout. We also implemented dynamic sizing for the online properties dialog to better fit the preview image and ensured portrait images scale correctly. Additionally, we fixed a crash caused by a missing method and implemented a "Delete Wallpaper" button with a confirmation dialog for already downloaded wallpapers.

## Changes Made

### `manpaper/ui/dialogs.py`

1.  **Moved Download Button**:
    -   Removed the separate `Adw.PreferencesGroup` for the download button.
    -   Added the button to a `Gtk.Box` in the `Adw.ToolbarView`'s **bottom bar**.
    -   This anchors the button to the bottom of the dialog, consistent with modern GNOME apps.

2.  **Fixed URL Row**:
    -   Added `url_row.set_subtitle_lines(2)` to both `create_online_properties_dialog` and `create_properties_dialog`.
    -   This prevents long URLs from expanding the row excessively or causing layout glitches.

3.  **Dynamic Dialog Width**:
    -   In `create_online_properties_dialog`, we now calculate a `desired_width` based on the wallpaper's aspect ratio (derived from `item.resolution`).
    -   **Portrait (aspect < 1)**: Set `preview_height` to 500px and clamp width to min 340px. This makes the image larger and the dialog narrower to fit.
    -   **Landscape (aspect >= 1)**: Set `preview_height` to 300px and clamp width to min 380px.
    -   `dialog.set_content_width(desired_width)` is used to resize the dialog.
    -   In `create_properties_dialog` (local), we set a fixed width of 420px for consistency.

4.  **Improved Image Scaling**:
    -   Set `hexpand=True` on the `Gtk.Picture` and its container box.
    -   Set `halign` and `valign` to `CENTER`.
    -   This ensures that portrait images (or any aspect ratio) properly fill the available space within the dialog, rather than being constrained to a small centered box.

5.  **Delete Button with Confirmation**:
    -   In `create_online_properties_dialog`, we now check `item.is_downloaded`.
    -   If downloaded, we show a **Delete Wallpaper** button (destructive style).
    -   Clicking "Delete Wallpaper" now opens a **Confirmation Dialog** ("Are you sure you want to delete...?").
    -   Confirming deletes the file; canceling does nothing.
    -   If not downloaded, we show the standard **Download Wallpaper** button (suggested style).

### `manpaper/app.py`

1.  **Restored Missing Method**:
    -   Restored `_on_apply_downloaded_wallpaper_clicked` which was accidentally removed during the threading refactor. This fixes the `AttributeError` when binding the download button.

2.  **Implemented Delete Handler**:
    -   Added `_on_delete_wallpaper_clicked` method.
    -   This method deletes the local file, updates the item's status (`is_downloaded=False`, `local_path=None`), emits `download-status-changed`, and reloads the wallpaper list.

## Verification
- **Online Properties**: Open an online wallpaper's properties.
    -   **Landscape**: The dialog should be wider to accommodate the image.
    -   **Portrait**: The dialog should be narrower and taller, with a larger image.
    -   **Download Button**: Should be at the bottom.
- **Local Properties**: Open a local URL wallpaper's properties. The dialog should be a consistent width (420px).
- **Download Button**: Clicking the download button (or seeing it update) should no longer crash the application.
- **Delete Functionality**:
    1.  Download a wallpaper.
    2.  Open its properties again.
    3.  Click "Delete Wallpaper".
    4.  **Verify Confirmation Dialog**: Ensure a dialog asks for confirmation.
    5.  Click "Cancel" -> Nothing happens.
    6.  Click "Delete" -> File is deleted, UI updates.
