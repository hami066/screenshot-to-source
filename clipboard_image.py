"""Read image bytes from the Windows clipboard on explicit paste."""

import ctypes
import io
import sys
import time
from ctypes import wintypes

from PIL import Image

from catalog import IMAGE_BYTE_LIMIT
from matcher import MAX_PIXELS


class ClipboardImageError(ValueError):
    pass


class WindowsClipboard:
    def __init__(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.open = self._function(user, "OpenClipboard", wintypes.BOOL, wintypes.HWND)
        self.close = self._function(user, "CloseClipboard", wintypes.BOOL)
        self.available = self._function(user, "IsClipboardFormatAvailable", wintypes.BOOL, wintypes.UINT)
        self.get_data = self._function(user, "GetClipboardData", wintypes.HANDLE, wintypes.UINT)
        self.register = self._function(user, "RegisterClipboardFormatW", wintypes.UINT, wintypes.LPCWSTR)
        self.size = self._function(kernel, "GlobalSize", ctypes.c_size_t, wintypes.HANDLE)
        self.lock = self._function(kernel, "GlobalLock", wintypes.LPVOID, wintypes.HANDLE)
        self.unlock = self._function(kernel, "GlobalUnlock", wintypes.BOOL, wintypes.HANDLE)

    @staticmethod
    def _function(library, name, result, *arguments):
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
        return function

    def image_payloads(self):
        formats = (
            (self.register("PNG"), "PNG"),
            (self.register("image/png"), "PNG"),
            (17, "DIB"),  # CF_DIBV5
            (8, "DIB"),   # CF_DIB
            (self.register("JFIF"), "JPEG"),
            (self.register("image/jpeg"), "JPEG"),
            (self.register("image/webp"), "WEBP"),
        )
        for attempt in range(3):
            if self.open(None):
                break
            if attempt < 2:
                time.sleep(0.04)
        else:
            raise ClipboardImageError("剪贴板正在被占用，请稍后再粘贴。")

        try:
            oversized = False
            for format_id, decoder in formats:
                if not format_id or not self.available(format_id):
                    continue
                handle = self.get_data(format_id)
                size = self.size(handle) if handle else 0
                oversized = oversized or size > IMAGE_BYTE_LIMIT
                if not 0 < size <= IMAGE_BYTE_LIMIT:
                    continue
                pointer = self.lock(handle)
                if pointer:
                    try:
                        payload = ctypes.string_at(pointer, size)
                    finally:
                        self.unlock(handle)
                    yield decoder, payload
            if oversized:
                raise ClipboardImageError("剪贴板图片太大，请重新截取所需区域。")
            if self.available(15):  # CF_HDROP
                raise ClipboardImageError("剪贴板里是文件。请把图片文件拖进来，或点「从文件选截图」。")
        finally:
            self.close()


def read_clipboard_image():
    if sys.platform != "win32":
        raise ClipboardImageError("剪贴板粘贴支持 Windows。也可以拖入图片文件。")
    payloads = WindowsClipboard().image_payloads()
    unusable_data = False
    try:
        for decoder, payload in payloads:
            try:
                image = Image.open(io.BytesIO(payload), formats=(decoder,))
                if image.width * image.height <= MAX_PIXELS:
                    return image
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
            unusable_data = True
    finally:
        payloads.close()
    if unusable_data:
        raise ClipboardImageError("这张截图太大或格式无法读取。请重新截取所需区域。")
    raise ClipboardImageError("剪贴板里没有图像。请重新截图或用「复制图片」，再按 Ctrl+V。")
