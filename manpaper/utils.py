import subprocess
import re
import json
import gi
gi.require_version('Gdk', '4.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gdk, Gio

from .config import BACKEND_PROCESSES

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
        match = re.search(r'Monitor .*\s*size: (\d+)x(\d+)', result.stdout)
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
        
        mpv_fill_type = app_settings.get_string('mpvpaper-fill-type')
        video_opts = ""
        if mpv_fill_type == "Crop":
            video_opts = "--panscan=1 --window-maximized=yes"

        if not socket_path:
            return None
        
        opts = []
        if video_opts:
            opts.append(video_opts)
        opts.append(audio_opts)
        opts.append(f"input-ipc-server={socket_path}")
        
        opts_str = " ".join(opts)

        return f'mpvpaper -vs -o "{opts_str}" ALL "{path}"'
    return None