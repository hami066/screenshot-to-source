"""Windows Shell operations for local files and desktop notices."""

import ctypes
import subprocess
import sys
from ctypes import wintypes


def reveal_file(path):
    """Select an already-validated local file in the system file manager."""
    if sys.platform == "darwin":
        try:
            subprocess.run(["/usr/bin/open", "-R", str(path)], check=True, timeout=5, capture_output=True)
        except subprocess.SubprocessError as error:
            raise OSError("Unable to reveal the file in Finder.") from error
        return

    com = ctypes.oledll.ole32
    shell = ctypes.oledll.shell32
    release = ctypes.windll.ole32.CoTaskMemFree
    release.argtypes = (ctypes.c_void_p,)
    release.restype = None
    com.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    shell.SHParseDisplayName.argtypes = (
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
    )
    shell.SHOpenFolderAndSelectItems.argtypes = (
        ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
    )
    item = ctypes.c_void_p()
    com.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    try:
        shell.SHParseDisplayName(str(path), None, ctypes.byref(item), 0, None)
        shell.SHOpenFolderAndSelectItems(item, 0, None, 0)
    finally:
        release(item)
        ctypes.windll.ole32.CoUninitialize()


def native_window(widget):
    ancestor = ctypes.windll.user32.GetAncestor
    ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    ancestor.restype = wintypes.HWND
    return ancestor(widget.winfo_id(), 2)  # GA_ROOT


class MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    )


def show_corner_window(window, owner, width, height, margin):
    """Show a Tk window near its owner's taskbar without taking keyboard focus."""
    user = ctypes.windll.user32
    monitor_from_window = user.MonitorFromWindow
    monitor_from_window.argtypes = (wintypes.HWND, wintypes.DWORD)
    monitor_from_window.restype = wintypes.HMONITOR
    monitor_info = user.GetMonitorInfoW
    monitor_info.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
    monitor_info.restype = wintypes.BOOL
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    monitor = monitor_from_window(native_window(owner), 2)  # MONITOR_DEFAULTTONEAREST
    if monitor_info(monitor, ctypes.byref(info)):
        right, bottom = info.work.right, info.work.bottom
    else:
        right, bottom = owner.winfo_screenwidth(), owner.winfo_screenheight()
    window.geometry(f"{width}x{height}")
    window.update_idletasks()
    hwnd = native_window(window)
    if not hwnd:
        window.geometry(f"{width}x{height}+{max(0, right - width - margin)}+{max(0, bottom - height - margin)}")
        window.deiconify()
        return
    get_style, set_style = user.GetWindowLongW, user.SetWindowLongW
    get_style.argtypes = (wintypes.HWND, ctypes.c_int)
    get_style.restype = ctypes.c_long
    set_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
    set_style.restype = ctypes.c_long
    extended_style = -20  # GWL_EXSTYLE
    no_activate, tool_window = 0x08000000, 0x00000080
    set_style(hwnd, extended_style, get_style(hwnd, extended_style) | no_activate | tool_window)
    window.deiconify()
    position = user.SetWindowPos
    position.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.UINT)
    position.restype = wintypes.BOOL
    position(hwnd, -1, right - width - margin, bottom - height - margin, width, height, 0x0010 | 0x0040)
