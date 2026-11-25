"""Local artwork and desktop widget styles."""

import ctypes
import sys
from dataclasses import dataclass
from tkinter import ttk

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageTk

FONT = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
BODY = -15
DETAIL = -14
SECTION = -17
TITLE = -36
BUTTONS = {
    "open": (135, 38), "demo": (106, 34), "paste": (118, 38), "search": (112, 38), "clear": (56, 38),
    "compare": (128, 38), "cancel": (88, 27), "remember": (96, 36), "reveal": (138, 36),
    "appearance": (132, 34), "formats": (115, 38), "format_apply": (90, 38), "format_cancel": (72, 38),
}
APPEARANCES = {"system": "跟随系统", "light": "浅色", "dark": "深色"}
PREFERENCES_KEY = r"Software\ScreenshotToSource"


@dataclass(frozen=True)
class Palette:
    dark: bool
    base: str
    caption: str
    sidebar: str
    text: str
    muted: str
    disabled: str
    panel: str
    panel_edge: str
    preview: str
    hover: str
    selected: str
    accent: str
    primary: str
    primary_hover: str


DARK = Palette(True, "#101320", "#141827", "#171c2b", "#f3f5fc", "#aeb7cf", "#75829f", "#181e2e",
               "#30394f", "#121827", "#27324b", "#243956", "#9bbcff", "#1b63e7", "#286ff2")
LIGHT = Palette(False, "#fafbfe", "#ffffff", "#ffffff", "#161b28", "#565f73", "#757f94", "#ffffff",
                "#e0e5ee", "#f2f4f9", "#ecf2ff", "#e8f0ff", "#1759c6", "#0965ed", "#0757ce")


def enable_windows_dpi():
    """Ask Windows for native pixels before Tk creates its first window."""
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = (ctypes.c_void_p,)
        setter.restype = ctypes.c_int
        setter(ctypes.c_void_p(-2))  # DPI_AWARENESS_CONTEXT_SYSTEM_AWARE
    except AttributeError:
        user32.SetProcessDPIAware()


def display_scale(window):
    if sys.platform == "darwin":
        return 1.0  # Aqua uses logical points and handles Retina backing pixels.
    return window.winfo_fpixels("1i") / 96


def desktop_animation_enabled():
    if sys.platform == "win32":
        enabled = ctypes.c_int()
        return bool(ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0) and enabled.value)
    if sys.platform == "darwin":
        from AppKit import NSWorkspace

        return not NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
    return False


def load_appearance():
    if sys.platform == "darwin":
        from Foundation import NSUserDefaults

        mode = NSUserDefaults.standardUserDefaults().stringForKey_("Appearance")
        return mode if mode in APPEARANCES else "system"
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCES_KEY) as key:
                mode = winreg.QueryValueEx(key, "Appearance")[0]
                if isinstance(mode, str) and mode in APPEARANCES:
                    return mode
        except OSError:
            pass
    return "system"


def save_appearance(mode):
    if sys.platform == "darwin":
        from Foundation import NSUserDefaults

        NSUserDefaults.standardUserDefaults().setObject_forKey_(mode, "Appearance")
        return
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PREFERENCES_KEY) as key:
                winreg.SetValueEx(key, "Appearance", 0, winreg.REG_SZ, mode)
        except OSError:
            pass


def system_theme():
    if sys.platform == "darwin":
        from Foundation import NSUserDefaults

        return DARK if NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle") == "Dark" else LIGHT
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return LIGHT if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else DARK
        except OSError:
            pass
    return LIGHT


def style_caption(root, palette):
    if sys.platform != "win32":
        return
    window = ctypes.windll.user32.GetAncestor
    window.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    window.restype = ctypes.c_void_p
    hwnd = window(root.winfo_id(), 2)
    if not hwnd:
        return
    setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
    setter.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)
    setter.restype = ctypes.c_long

    def set_attribute(key, value):
        data = ctypes.c_int(value)
        return setter(hwnd, key, ctypes.byref(data), ctypes.sizeof(data))

    if set_attribute(20, int(palette.dark)) != 0:
        set_attribute(19, int(palette.dark))
    for key, color in ((35, palette.caption), (36, palette.text)):
        r, g, b = ImageColor.getrgb(color)
        set_attribute(key, r | g << 8 | b << 16)


def paint_backdrop(palette, size, px):
    width, height = size
    image = Image.new("RGB", size, palette.base)
    nav_height = px(56)
    band_height = min(height - nav_height, px(170))
    if band_height > 0:
        x = np.linspace(-1, 1, width, dtype=np.float32)[None, :]
        y = np.linspace(0, 1, band_height, dtype=np.float32)[:, None]
        strength = (1 - y)**2.15 * (.30 + .70 * np.exp(-2.5 * x**2))
        mask = Image.fromarray(np.rint(strength * 255).astype(np.uint8))
        tint = "#303e81" if palette.dark else "#b8c9ff"
        image.paste(tint, (0, nav_height, width, nav_height + band_height), mask)
    image.paste(palette.caption, (0, 0, width, min(nav_height, height)))
    if nav_height < height:
        ImageDraw.Draw(image).line((0, nav_height - 1, width, nav_height - 1), fill=palette.panel_edge)
    return image


def rounded_surface(size, fill, radius, *, edge=None, bottom=None):
    width, height = size
    factor = 3
    surface = Image.new("RGBA", (width * factor, height * factor))
    if bottom:
        mask = Image.new("L", surface.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, surface.width - 1, surface.height - 1),
                                               radius * factor, fill=255)
        ramp = Image.linear_gradient("L").resize(surface.size)
        surface = Image.composite(Image.new("RGBA", surface.size, bottom),
                                  Image.new("RGBA", surface.size, fill), ramp)
        surface.putalpha(mask)
    if edge or (fill and not bottom):
        ImageDraw.Draw(surface).rounded_rectangle(
            (0, 0, width * factor - 1, height * factor - 1),
            radius * factor, fill=None if bottom else fill, outline=edge, width=factor,
        )
    return surface.resize(size, Image.Resampling.LANCZOS)


def icon(name, color, size=18, *, background=None, centered=False):
    image = Image.new("RGBA", (72, 72))
    draw = ImageDraw.Draw(image)
    point = lambda x, y: (round(x * 4), round(y * 4))

    def line(*coords):
        draw.line([point(*pair) for pair in coords], fill=color, width=5, joint="curve")

    def box(x, y, right, bottom, radius=1.5):
        draw.rounded_rectangle((*point(x, y), *point(right, bottom)), radius * 4, outline=color, width=5)

    if name == "chevron":
        line((5, 7.5), (9, 11.5), (13, 7.5))
    elif name == "crop":
        for x, y, dx, dy in ((2, 2, 1, 1), (16, 2, -1, 1), (2, 16, 1, -1), (16, 16, -1, -1)):
            line((x + 4 * dx, y), (x, y), (x, y + 4 * dy))
        box(6, 6, 12, 12, 1)
    elif name == "tick":
        line((3.8, 9), (7.4, 12.6), (14.2, 5.7))
    elif name == "folder":
        line((2, 14.5), (2, 4), (6, 4), (8, 6), (15.5, 6), (15.5, 8))
        line((2, 14.5), (14, 14.5), (16, 8), (4.5, 8), (2, 14.5))
    elif name == "picture":
        box(2.1, 3.5, 15.8, 14.5)
        line((2.5, 13), (6.3, 9.4), (9.2, 12), (12, 8.9), (15.2, 11.8))
        draw.ellipse((*point(5.3, 5.4), *point(7.6, 7.7)), fill=color)
    elif name == "search":
        draw.ellipse((*point(2.3, 2.3), *point(11.8, 11.8)), outline=color, width=5)
        line((10.6, 10.6), (15.7, 15.7))
    elif name == "match":
        box(3, 3, 15, 15, 2)
        line((6, 9), (8.2, 11.2), (12.3, 7))
    elif name == "clipboard":
        line((8, 3), (4, 3), (3, 4), (3, 14.5), (7, 14.5))
        box(8, 6, 15, 15.3)
        box(5, 1.5, 11, 4.7, 1)
    elif name == "trash":
        line((2.5, 5), (15.5, 5))
        line((6, 4.5), (6.8, 2.5), (11.2, 2.5), (12, 4.5))
        line((4.5, 5.5), (5.3, 15.4), (12.7, 15.4), (13.5, 5.5))
        line((7.4, 7.5), (7.7, 13.2))
        line((10.6, 7.5), (10.3, 13.2))
    elif name == "play":
        draw.polygon([point(5, 2.5), point(15, 9), point(5, 15.5)], fill=color)
    elif name == "feather":
        draw.polygon([point(*p) for p in ((4, 17), (4.3, 10), (6.7, 5.4), (10.4, 2.2), (16.5, .8),
                                          (14, 6.7), (11.4, 8.6), (12.7, 8.6), (8.8, 12.4),
                                          (6.3, 13.1))], fill="#468ce9")
        draw.polygon([point(*p) for p in ((4.6, 14.3), (6, 7.7), (10.5, 3.3), (16.5, .8),
                                          (12.2, 5.2), (9.4, 8.5))], fill="#a6d6ff")
        line((3.4, 17), (6.4, 11.5), (10.1, 6.7), (14, 3.3))
    else:
        if background:
            draw.rounded_rectangle((*point(1.5, 1), *point(16.5, 17)), 12, fill=background)
        if name == "pdf":
            line((5.1, 12.7), (8.3, 8.2), (9.1, 4.1), (10.1, 7.5), (13.5, 11.4),
                 (10.3, 11.2), (5.1, 12.7))
        elif name == "raster":
            box(4, 5, 14, 13, 1)
            line((4.5, 12.5), (7.5, 9.1), (9, 10.7), (11.3, 8.4), (13.6, 11))
        elif name == "ps":
            line((4.5, 13), (4.5, 5.4), (8, 5.4), (9, 6.5), (9, 8.1), (8, 9), (4.5, 9))
            line((13.8, 8.4), (11.5, 8.4), (10.8, 9.4), (11.5, 10.4), (13.3, 10.8), (13.9, 11.8),
                 (13.2, 12.8), (10.7, 12.8))
        elif name == "ai":
            line((4.3, 12.7), (7.5, 5.4), (10.6, 12.7))
            line((5.6, 10), (9.3, 10))
            line((13, 8.8), (13, 12.7))
            draw.ellipse((*point(12.3, 5.8), *point(13.7, 7.2)), fill=color)
        else:
            line((6, 4.6), (10, 4.6), (13, 7.7), (13, 13.7), (6, 13.7), (6, 4.6))
            line((10, 4.6), (10, 7.7), (13, 7.7))
    if centered:
        ink = image.crop(image.getbbox())
        image = Image.new("RGBA", image.size)
        image.paste(ink, ((image.width - ink.width) // 2, (image.height - ink.height) // 2))
    return image.resize((size, size), Image.Resampling.LANCZOS)


class DesktopStyles:
    def __init__(self, root):
        self.root = root
        self.scale = display_scale(root)
        self.style = ttk.Style(root)
        self.surfaces = {}
        for name, palette in (("night", DARK), ("day", LIGHT)):
            self.style.theme_create(name, parent="clam")
            self.style.theme_use(name)
            self.configure(palette)

    def px(self, value):
        return round(value * self.scale)

    def button_size(self, name):
        width, height = BUTTONS[name]
        return self.px(width), self.px(height)

    @staticmethod
    def button_style(name):
        return f"App{name.title()}.TButton"

    def button(self, name, p):
        size = self.button_size(name)
        style = self.button_style(name)
        primary = name in ("compare", "format_apply")
        quiet = name in ("clear", "cancel", "demo", "remember")
        base = p.primary if primary else None if quiet else p.panel
        edge = None if primary or quiet else p.panel_edge
        hover = p.primary_hover if primary else p.hover
        images = [rounded_surface(size, fill, size[1] // 2, edge=line) for fill, line in (
            (base, edge), (p.preview if primary else None, None), (hover, edge), (hover, edge), (base, p.accent),
        )]
        photos = [ImageTk.PhotoImage(image, master=self.root) for image in images]
        self.surfaces[p.dark, name] = (images, photos)
        element = f"{style}.surface"
        self.style.element_create(element, "image", photos[0], ("disabled", photos[1]), ("pressed", photos[2]),
                                  ("focus", photos[4]), ("active", photos[3]), sticky="nswe")
        self.style.layout(style, [(element, {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "nswe"})]})])
        self.style.configure(style, anchor="center", space=self.px(5), background=p.base,
                             foreground="#ffffff" if primary else p.text,
                             font=(FONT, self.px(BODY if primary else DETAIL), "bold" if primary else "normal"))
        self.style.map(style, foreground=[("disabled", p.disabled)])

    def draw_button(self, name, palette, background):
        images, photos = self.surfaces[palette.dark, name]
        for surface, photo in zip(images, photos):
            composite = background.copy()
            composite.alpha_composite(surface)
            photo.paste(composite)

    def configure(self, p):
        style = self.style
        style.configure(".", font=(FONT, self.px(BODY)), background=p.base, foreground=p.text, borderwidth=0)
        for name in BUTTONS:
            self.button(name, p)
        style.configure("Results.Treeview", background=p.sidebar, fieldbackground=p.sidebar, foreground=p.text,
                        rowheight=self.px(36), borderwidth=0, relief="flat", padding=0)
        style.layout("Results.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        header = p.sidebar
        style.configure("Results.Treeview.Heading", background=header, foreground=p.muted, relief="flat",
                        font=(FONT, self.px(DETAIL)), padding=(self.px(4), self.px(7)),
                        lightcolor=header, darkcolor=header, bordercolor=header)
        style.map("Results.Treeview", background=[("selected", p.selected)],
                  foreground=[("selected", p.text)])
        style.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "nswe", "children": [
            ("Vertical.Scrollbar.thumb", {"sticky": "nswe", "expand": "1"}),
        ]})])
        style.configure("Slim.Vertical.TScrollbar", background=p.panel_edge, troughcolor=p.sidebar,
                        bordercolor=p.panel_edge, lightcolor=p.panel_edge, darkcolor=p.panel_edge, width=self.px(6))
        style.configure("Path.TEntry", fieldbackground=p.panel, foreground=p.text, bordercolor=p.panel,
                        font=(FONT, self.px(DETAIL)),
                        lightcolor=p.panel, darkcolor=p.panel, padding=self.px(3), selectbackground=p.selected,
                        selectforeground=p.text)
        style.map("Path.TEntry", fieldbackground=[("readonly", p.panel)], foreground=[("readonly", p.text)])
        style.configure("Filter.TEntry", fieldbackground=p.preview, foreground=p.text,
                        bordercolor=p.panel_edge, lightcolor=p.preview, darkcolor=p.preview,
                        font=(FONT, self.px(DETAIL)), padding=(self.px(9), self.px(7)),
                        selectbackground=p.selected, selectforeground=p.text)
        style.map("Filter.TEntry", bordercolor=[("focus", p.accent)])

    def use(self, palette):
        self.style.theme_use("night" if palette.dark else "day")
