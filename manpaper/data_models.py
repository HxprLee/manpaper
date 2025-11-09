import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

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
    title = GObject.Property(type=str)

    def __init__(self, path, title=None):
        super().__init__()
        self.path = path
        self.title = title

# --- Online Wallpaper Item ---
class OnlineWallpaperItem(GObject.Object):
    """A GObject representing a single wallpaper from an online source."""
    __gsignals__ = {
        'preview-size-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'download-status-changed': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_BOOLEAN, GObject.TYPE_STRING))
    }
    wall_id = GObject.Property(type=str)
    thumbnail_url = GObject.Property(type=str)
    full_url = GObject.Property(type=str)
    purity = GObject.Property(type=str)
    path = GObject.Property(type=str) # Added for consistency with WallpaperItem
    title = GObject.Property(type=str) # Added for consistency with WallpaperItem
    is_downloaded = GObject.Property(type=bool, default=False)
    local_path = GObject.Property(type=str, default=None)

    def __init__(self, wall_id, thumbnail_url, full_url, purity, is_downloaded=False, local_path=None):
        super().__init__()
        self.wall_id = wall_id
        self.thumbnail_url = thumbnail_url
        self.full_url = full_url
        self.purity = purity
        self.path = full_url # Use full_url as path
        self.title = wall_id # Use wall_id as title by default
        self.is_downloaded = is_downloaded
        self.local_path = local_path

# --- GObject Helper for Download Queue ---
class DownloadQueueItem(GObject.Object):
    """A GObject for items in the download queue popover."""
    text = GObject.Property(type=str)
    status = GObject.Property(type=str)
    online_wallpaper_item = GObject.Property(type=object)

    def __init__(self, text, status, online_wallpaper_item):
        super().__init__()
        self.text = text
        self.status = status
        self.online_wallpaper_item = online_wallpaper_item
