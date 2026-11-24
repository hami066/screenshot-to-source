"""Desktop layout for Screenshot to Source."""

import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageTk
from tkinterdnd2 import DND_FILES

from desktop_notice import CompletionNotice
from desktop_theme import (
    APPEARANCES, DARK, DETAIL, FONT, LIGHT, SECTION, TITLE, DesktopStyles, icon, load_appearance,
    paint_backdrop, rounded_surface, save_appearance, style_caption, windows_theme,
)


class ProgressMeter(tk.Canvas):
    def __init__(self, parent, value):
        super().__init__(parent, highlightthickness=0, borderwidth=0)
        self.value = value
        self.mode = "determinate"
        self.animation = None
        self.segment = 0
        self.track = self.fill = self.surface = self.sheen = None
        self.value.trace_add("write", self.paint)
        self.display = self.create_image(0, 0, anchor="nw")

    def decorate(self, area, palette):
        self.track = area.copy()
        self.track.alpha_composite(rounded_surface(area.size, palette.panel_edge, 3))
        self.palette = palette
        self.fill = None
        height = area.height
        sheen_width = height * 10
        self.sheen = Image.new("RGBA", (sheen_width, height))
        draw = ImageDraw.Draw(self.sheen)
        for column in range(sheen_width):
            strength = 1 - abs(2 * column / (sheen_width - 1) - 1)
            draw.line((column, 0, column, height - 1), fill=(209, 237, 255, round(178 * strength**2)))
        self.paint()

    def set_mode(self, mode):
        self.mode = mode
        self.paint()

    def start(self, interval):
        self.stop()
        self.segment = 0

        def tick():
            self.animation = self.after(interval, tick)
            self.segment = (self.segment + 4) % 200
            self.paint()

        tick()

    def stop(self):
        if self.animation is not None:
            self.after_cancel(self.animation)
            self.animation = None
            self.paint()

    def paint(self, *_):
        if self.track is None:
            return
        image = self.track.copy()
        width, height = image.size
        if self.mode == "indeterminate":
            length = width // 4
            left = round((100 - abs(100 - self.segment)) * (width - length) / 100)
        else:
            length = round(width * self.value.get() / 100)
            left = 0
        if length >= 2:
            if self.fill is None or self.fill.size != (length, height):
                self.fill = rounded_surface((length, height), self.palette.primary, min(height // 2, length // 2),
                                            bottom=self.palette.primary_hover)
            image.alpha_composite(self.fill, (left, 0))
            if self.animation is not None:
                sheen_left = round((width + self.sheen.width) * self.segment / 200) - self.sheen.width
                start = max(left + 3, sheen_left)
                end = min(left + length - 3, sheen_left + self.sheen.width)
                if start < end:
                    shine = self.sheen.crop((start - sheen_left, 1, end - sheen_left, height - 1))
                    image.alpha_composite(shine, (start, 1))
        self.surface = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self.display, image=self.surface)


class DesktopView(tk.Canvas):
    def __init__(self, app, preview_type):
        root = app.root
        super().__init__(root, highlightthickness=0, borderwidth=0)
        self.app = app
        self.styles = DesktopStyles(root)
        self.notice = CompletionNotice(root, self.styles.px)
        self.palette = None
        self.pictures = {}
        self.icons = {}
        self.labels = {}
        self.pack(fill="both", expand=True)
        self.create_image(0, 0, anchor="nw", tags="backdrop")
        self.create_image(0, 0, anchor="nw", tags="brand")
        self.create_image(0, 0, anchor="nw", tags="path-surface")
        self.create_line(0, 0, 0, 0, tags="sidebar-rule")
        self.label_widths = {}

        self.label("title", "截图找原稿", size=TITLE, bold=True)
        self.label("subtitle", "在本机用截图定位设计原稿", muted=True)
        self.label("scope-heading", "搜索范围", size=SECTION, bold=True)
        self.label("scope", app.project_line, muted=True)
        self.label("results", "对比结果", size=SECTION)
        self.label("summary", app.result_summary, muted=True)
        self.label("progress", app.progress_text, muted=True)
        self.label("status", app.status, muted=True)
        self.label("query", "客户截图", bold=True)
        self.label("match", "原稿预览", bold=True)
        self.label("evidence", app.evidence_line, muted=True)
        self.label("location", app.location_label)

        for name, text, command, glyph in (
            ("open", "选择文件夹…", app.choose_project, "folder"),
            ("demo", "试用样例", app.open_demo, None),
            ("paste", "粘贴截图", app.paste_query, "clipboard"),
            ("search", "选择截图…", app.choose_query, "picture"),
            ("clear", "清除", app.clear_query, None),
            ("compare", "开始对比", app.start_compare, None),
            ("cancel", "取消对比", app.cancel_compare, None),
            ("remember", "记住原稿…", app.remember_source, None),
            ("reveal", "在文件夹中定位", app.reveal_selected_file, None),
        ):
            app.buttons[name] = ttk.Button(self, text=text, command=command, compound="left", style=self.styles.button_style(name))
            if glyph:
                self.icons[name] = glyph
        self.appearance = tk.StringVar(master=self, value=load_appearance())
        self.appearance_menu = tk.Menu(self, tearoff=False, font=(FONT, self.styles.px(DETAIL)))
        for mode, label in APPEARANCES.items():
            self.appearance_menu.add_radiobutton(label=label, variable=self.appearance, value=mode,
                                                command=self.select_appearance)
        app.buttons["appearance"] = ttk.Button(
            self, text=self.appearance_label(), command=self.open_appearance,
            compound="right", style=self.styles.button_style("appearance"),
        )
        self.icons["appearance"] = "chevron"
        app.buttons["include"] = ttk.Checkbutton(self, variable=app.include_images, style="Filter.TCheckbutton",
                                                text=" 同时搜索 PNG、JPG 等成品图")
        app.progress = ProgressMeter(self, app.progress_value)
        app.rows = {}
        app.tree = ttk.Treeview(self, columns=("match",), show="tree headings", selectmode="browse",
                                style="Results.Treeview")
        app.tree.heading("#0", text="文件名", anchor="w")
        app.tree.heading("match", text="匹配状态")
        app.tree.column("#0", minwidth=self.styles.px(120))
        status_width = self.styles.px(80)
        app.tree.column("match", width=status_width, minwidth=status_width, anchor="center", stretch=False)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=app.tree.yview, style="Slim.Vertical.TScrollbar")
        app.tree.configure(yscrollcommand=self.set_scroll)
        app.tree.bind("<<TreeviewSelect>>", app.select)
        app.query_preview = preview_type(self, "粘贴或拖入截图", query=True)
        app.query_preview.drop_target_register(DND_FILES)
        app.query_preview.dnd_bind("<<Drop>>", app.drop)
        app.match_preview = preview_type(self, "对比后显示匹配画面")
        self.path_entry = ttk.Entry(self, textvariable=app.location_path, state="readonly", style="Path.TEntry")
        app.location_path.trace_add("write", self.update_path)
        app.progress_text.trace_add("write", lambda *_: self.update_progress())

        self.window_icon = ImageTk.PhotoImage(icon("crop", "#2158a8", self.styles.px(32)), master=root)
        root.iconphoto(True, self.window_icon)
        self.refresh_theme()
        self.bind("<Configure>", self.schedule_layout)
        root.bind("<Map>", self.on_map, add="+")
        root.after(1000, self.follow_system_theme)

    def label(self, name, text, *, size=DETAIL, bold=False, muted=False):
        font = tkfont.Font(root=self, family=FONT, size=self.styles.px(size), weight="bold" if bold else "normal")
        item = self.create_text(0, 0, anchor="nw", font=font,
                                tags=name, justify="left")
        if isinstance(text, tk.Variable):
            def update(*_):
                value = text.get()
                if name in self.label_widths:
                    value = self.fit_line(value, font, self.label_widths[name])
                self.itemconfigure(item, text=value)

            text.trace_add("write", update)
            update()
        else:
            self.itemconfigure(item, text=text)
        self.labels[name] = (muted, font)

    @staticmethod
    def fit_line(text, font, width):
        if font.measure(text) <= width:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if font.measure(text[:middle] + "…") <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low] + "…"

    def fit_label(self, name, text, width):
        self.label_widths[name] = width
        self.itemconfigure(name, text=self.fit_line(text, self.labels[name][1], width))

    def on_map(self, event):
        if event.widget == self.app.root:
            self.after_idle(style_caption, self.app.root, self.palette)

    def follow_system_theme(self):
        if self.appearance.get() == "system":
            self.refresh_theme()
        self.after(1000, self.follow_system_theme)

    def appearance_label(self):
        return f"外观 · {APPEARANCES[self.appearance.get()]}"

    def open_appearance(self):
        button = self.app.buttons["appearance"]
        try:
            self.appearance_menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            self.appearance_menu.grab_release()

    def select_appearance(self):
        save_appearance(self.appearance.get())
        self.app.buttons["appearance"].configure(text=self.appearance_label())
        self.refresh_theme()

    def refresh_theme(self):
        mode = self.appearance.get()
        palette = windows_theme() if mode == "system" else DARK if mode == "dark" else LIGHT
        if palette != self.palette:
            self.apply_theme(palette)

    def apply_theme(self, palette):
        self.palette = palette
        self.styles.use(palette)
        self.configure(background=palette.base)
        self.app.root.configure(background=palette.base)
        style_caption(self.app.root, palette)
        self.appearance_menu.configure(background=palette.panel, foreground=palette.text,
                                       activebackground=palette.hover, activeforeground=palette.text,
                                       selectcolor=palette.accent)
        for name, (muted, _) in self.labels.items():
            self.itemconfigure(name, fill=palette.muted if muted else palette.text)
        small_icon = self.styles.px(16)
        for name, glyph in self.icons.items():
            photo = self.photo(f"icon-{name}", icon(glyph, palette.muted, small_icon))
            disabled = self.photo(f"icon-{name}-disabled", icon(glyph, palette.disabled, small_icon))
            self.app.buttons[name].configure(image=(photo, "disabled", disabled))
        self.itemconfigure("brand", image=self.photo("brand", icon("crop", palette.accent, self.styles.px(36))))
        self.itemconfigure("sidebar-rule", fill=palette.panel_edge)
        self.file_icons = {
            kind: self.photo(f"file-{kind}", icon(kind, palette.muted, small_icon))
            for kind in ("ps", "ai", "pdf", "raster", "file")
        }
        for row, record in self.app.rows.items():
            self.app.tree.item(row, image=self.file_icon(Path(record.export)))
        self.layout()

    def file_icon(self, path):
        suffix = path.suffix.lower()
        formats = {".psd": "ps", ".psb": "ps", ".ai": "ai", ".pdf": "pdf", ".svg": "file"}
        return self.file_icons[formats.get(suffix, "raster")]

    def photo(self, name, image):
        photo = ImageTk.PhotoImage(image, master=self)
        self.pictures[name] = photo
        return photo

    def schedule_layout(self, _event):
        if getattr(self, "layout_job", None) is None:
            self.layout_job = self.after(22, self.layout)

    def layout(self):
        self.layout_job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 200 or h < 200:
            return
        p = self.palette
        px = self.styles.px
        button_width = lambda name: self.styles.button_size(name)[0]
        margin = px(24)
        sidebar = min(px(356), max(px(304), w // 3))
        middle = sidebar + margin
        right = w - margin
        right_width = right - middle
        footer = h - px(56)
        card_bottom = footer - px(48)
        preview_top = px(264)
        preview_gap = px(16)
        preview_width = (right_width - preview_gap) // 2
        right_preview = middle + preview_width + preview_gap

        self.background = background = paint_backdrop(p, (w, h), sidebar, px)
        self.itemconfigure("backdrop", image=self.photo("backdrop", background))
        self.coords("brand", margin, px(28))
        self.coords("title", px(72), px(16))
        self.coords("subtitle", px(74), px(59))
        self.place_buttons(background, ("appearance",), right - button_width("appearance"), px(30), gap=0)

        self.coords("scope-heading", margin, px(120))
        self.coords("scope", margin, px(150))
        self.fit_label("scope", self.app.project_line.get(), sidebar - 2 * margin)
        self.place_buttons(background, ("open", "demo"), margin, px(176), gap=px(8))
        self.app.buttons["include"].place(x=margin, y=px(220), height=px(28))
        self.coords("sidebar-rule", margin, px(264), sidebar - margin, px(264))
        self.coords("results", margin, px(284))
        self.coords("summary", margin, px(314))
        self.fit_label("summary", self.app.result_summary.get(), sidebar - 2 * margin)
        self.tree_box = dict(x=margin, y=px(344), width=sidebar - 2 * margin, height=h - px(372))
        self.scroll_box = dict(x=sidebar - margin + px(4), y=px(376), width=px(6), height=h - px(404))
        status_width = self.app.tree.column("match", "width")
        self.app.tree.column("#0", width=self.tree_box["width"] - status_width)
        self.update_results()

        self.place_buttons(background, ("paste", "search", "clear"), middle, px(120), gap=px(8))
        self.place_buttons(background, ("compare",), right - button_width("compare"), px(120), gap=0)
        self.coords("status", middle, px(174))
        self.itemconfigure("status", width=right_width - px(96))
        self.cancel_position = (right - button_width("cancel"), px(168))
        progress_label_width = px(156)
        progress_width = right_width - progress_label_width - px(12)
        progress_y, progress_h = px(221), px(8)
        self.progress_box = dict(x=middle, y=progress_y, width=progress_width, height=progress_h)
        area = background.crop((middle, progress_y, middle + progress_width, progress_y + progress_h))
        self.app.progress.decorate(area.convert("RGBA"), p)
        self.coords("progress", middle + progress_width + px(12), px(213))
        self.fit_label("progress", self.app.progress_text.get(), progress_label_width)
        self.update_progress()

        self.coords("query", middle, preview_top - px(24))
        self.coords("match", right_preview, preview_top - px(24))
        self.coords("evidence", middle, card_bottom + px(8))
        self.fit_label("evidence", self.app.evidence_line.get(), right_width)
        preview_height = card_bottom - preview_top
        for x, preview in ((middle, self.app.query_preview), (right_preview, self.app.match_preview)):
            area = background.crop((x, preview_top, x + preview_width, card_bottom)).convert("RGBA")
            area.alpha_composite(rounded_surface(area.size, p.panel, px(14), edge=p.panel_edge, bottom=p.preview))
            preview.decorate(area, p)
            preview.place(x=x, y=preview_top, width=preview_width, height=preview_height)

        self.coords("location", middle, footer - px(18))
        gap = px(8)
        button_left = right - button_width("remember") - button_width("reveal") - gap
        path_width = button_left - gap - middle
        self.coords("path-surface", middle, footer)
        self.itemconfigure("path-surface", image=self.photo("path-surface", rounded_surface(
            (path_width, px(36)), p.panel, px(8), edge=p.panel_edge)))
        self.path_box = dict(x=middle + px(8), y=footer + px(4), width=path_width - px(16), height=px(28))
        self.path_buttons = (button_left, footer)
        self.update_path()

    def set_scroll(self, first, last):
        self.scroll.set(first, last)
        if hasattr(self, "scroll_box") and self.app.rows and (float(first) > 0 or float(last) < 1):
            self.scroll.place(**self.scroll_box)
        else:
            self.scroll.place_forget()

    def update_results(self):
        if not hasattr(self, "tree_box"):
            return
        if self.app.rows:
            self.app.tree.place(**self.tree_box)
        else:
            self.app.tree.place_forget()
        self.set_scroll(*self.app.tree.yview())

    def update_progress(self):
        if not hasattr(self, "progress_box"):
            return
        active = self.app.progress_text.get() != "等待开始"
        self.itemconfigure("progress", state="normal" if active else "hidden")
        if active:
            self.app.progress.place(**self.progress_box)
        else:
            self.app.progress.place_forget()
        if self.app.comparing:
            self.place_buttons(self.background, ("cancel",), *self.cancel_position, gap=0)
        else:
            self.app.buttons["cancel"].place_forget()

    def update_path(self, *_):
        if not hasattr(self, "path_box"):
            return
        visible = bool(self.app.location_path.get())
        for name in ("location", "path-surface"):
            self.itemconfigure(name, state="normal" if visible else "hidden")
        if visible:
            self.path_entry.place(**self.path_box)
            self.path_entry.after_idle(self.path_entry.xview_moveto, 1)
            self.place_buttons(self.background, ("remember", "reveal"), *self.path_buttons, gap=self.styles.px(8))
        else:
            self.path_entry.place_forget()
            for name in ("remember", "reveal"):
                self.app.buttons[name].place_forget()

    def place_buttons(self, background, names, x, y, *, gap):
        for name in names:
            width, height = self.styles.button_size(name)
            surface = background.crop((x, y, x + width, y + height)).convert("RGBA")
            self.styles.draw_button(name, self.palette, surface)
            self.app.buttons[name].place(x=x, y=y, width=width, height=height)
            x += width + gap
