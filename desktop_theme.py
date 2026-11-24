"""Local artwork and desktop widget styles."""

import ctypes
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tkinter import ttk

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageTk

FONT = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
BODY = -15
DETAIL = -14
SECTION = -18
TITLE = -30
BUTTONS = {
    "open": (132, 36), "demo": (92, 36), "paste": (124, 40), "search": (124, 40), "clear": (64, 40),
    "compare": (120, 40), "cancel": (88, 28), "remember": (96, 36), "reveal": (132, 36),
    "appearance": (148, 36), "formats": (188, 30),
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


DARK = Palette(True, "#0b2341", "#081b34", "#102b4c", "#f0f6ff", "#b4c8e2", "#829bb9", "#163553",
               "#355474", "#102947", "#23496d", "#194e84", "#a7cdf8", "#1769c6", "#1d76d6")
LIGHT = Palette(False, "#edf4fd", "#f5f9ff", "#e2edfb", "#102a4c", "#465f7d", "#607895", "#f6faff",
                "#bfcfe3", "#e5effb", "#d9e9fc", "#c4dfff", "#215baa", "#1a5fae", "#114e96")


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


@lru_cache(maxsize=3)
def header_mask(size, asset):
    if asset == "lens":
        path = Path(__file__).with_name("assets") / "frosted-lens.png"
        with Image.open(path) as source:
            return source.convert("L").resize(size, Image.Resampling.LANCZOS)
    width, height = size
    font_size = round(height * .85)
    try:
        font = ImageFont.truetype("segoeuib.ttf", font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    word = "search"
    bounds = [draw.textbbox((0, 0), letter, font=font, anchor="ls") for letter in word]
    widths = [draw.textlength(letter, font=font) for letter in word]
    top = min(box[1] for box in bounds)
    bottom = max(box[3] for box in bounds)
    baseline = (height - top - bottom) // 2
    blur = max(1, height * .035)
    inset = round(3 * blur) + 2
    x = inset - bounds[0][0]
    last_x = width - inset - bounds[-1][2]
    spacing = (last_x - x - sum(widths[:-1])) / (len(word) - 1)
    for letter, advance in zip(word, widths):
        draw.text((round(x), baseline), letter, font=font, fill=255, anchor="ls")
        x += advance + spacing
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    fade = np.linspace(.28, 1.0, width, dtype=np.float32)[None, :]
    return Image.fromarray((np.asarray(mask) * fade).astype(np.uint8))


def paint_backdrop(palette, size, split, px):
    width, height = size
    image = Image.new("RGB", size, palette.base)
    draw = ImageDraw.Draw(image)
    header = px(96)
    tint = "#1a4877" if palette.dark else "#d1e4fa"
    wash = Image.linear_gradient("L").transpose(Image.Transpose.ROTATE_90).resize((width, header))
    band = Image.new("RGB", (width, header), palette.caption)
    band.paste(tint, (0, 0, width, header), wash)
    art_right = width - px(24 + BUTTONS["appearance"][0] + 16)
    for asset, dimensions, position, strength in (
        ("search", (px(208), px(66)), (art_right - px(302), px(15)), .30),
        ("lens", (px(92), px(92)), (art_right - px(92), px(2)), .49),
    ):
        mask = header_mask(dimensions, asset).point(lambda value: round(value * strength))
        band.paste(palette.accent, (*position, position[0] + dimensions[0], position[1] + dimensions[1]), mask)
    image.paste(band, (0, 0))
    draw.rectangle((0, header + 1, split, height), fill=palette.sidebar)
    draw.line((0, header, width, header), fill=palette.panel_edge)
    draw.line((split, header, split, height), fill=palette.panel_edge)
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


def icon(name, color, size=18, *, background=None):
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
    elif name in ("checked", "unchecked"):
        draw.rounded_rectangle((*point(2, 2), *point(16, 16)), 12, outline=color, width=5, fill=background)
        if name == "checked":
            line((5.2, 9), (8, 11.7), (13, 6.6))
    elif name == "folder":
        line((2, 14.5), (2, 4), (6, 4), (8, 6), (15.5, 6), (15.5, 8))
        line((2, 14.5), (14, 14.5), (16, 8), (4.5, 8), (2, 14.5))
    elif name == "picture":
        box(2.1, 3.5, 15.8, 14.5)
        line((2.5, 13), (6.3, 9.4), (9.2, 12), (12, 8.9), (15.2, 11.8))
        draw.ellipse((*point(5.3, 5.4), *point(7.6, 7.7)), fill=color)
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
        primary = name == "compare"
        quiet = name in ("clear", "cancel", "demo", "remember")
        base = p.primary if primary else None if quiet else p.panel
        edge = None if primary or quiet else p.panel_edge
        hover = p.primary_hover if primary else p.hover
        images = [rounded_surface(size, fill, self.px(10), edge=line, bottom=bottom) for fill, line, bottom in (
            (base, edge, p.primary_hover if primary else None),
            (None, None, None), (hover, edge, None), (hover, edge, None), (base, p.accent, None),
        )]
        photos = [ImageTk.PhotoImage(image, master=self.root) for image in images]
        self.surfaces[p.dark, name] = (images, photos)
        element = f"{style}.surface"
        self.style.element_create(element, "image", photos[0], ("disabled", photos[1]), ("pressed", photos[2]),
                                  ("focus", photos[4]), ("active", photos[3]), sticky="nswe")
        self.style.layout(style, [(element, {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "nswe"})]})])
        self.style.configure(style, anchor="center", background=p.base, foreground="#ffffff" if primary else p.text,
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
        self.style_checkbox(p)
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

    def style_checkbox(self, p):
        photos = [
            ImageTk.PhotoImage(icon(name, color, self.px(16)), master=self.root)
            for name, color in (("unchecked", p.muted), ("checked", p.accent), ("unchecked", p.disabled))
        ]
        self.surfaces[p.dark, "checkbox"] = photos
        self.style.element_create("Filter.indicator", "image", photos[0],
                                  ("selected", photos[1]), ("disabled", photos[2]))
        self.style.layout("Filter.TCheckbutton", [("Checkbutton.focus", {"sticky": "nswe", "children": [
            ("Filter.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": ""}),
        ]})])
        self.style.configure("Filter.TCheckbutton", background=p.sidebar, foreground=p.muted,
                             font=(FONT, self.px(DETAIL)), focuscolor=p.accent)

    def use(self, palette):
        self.style.theme_use("night" if palette.dark else "day")
