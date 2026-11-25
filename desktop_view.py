"""Desktop layout for Screenshot to Source."""

import tkinter as tk
from pathlib import Path
from time import monotonic
from tkinter import font as tkfont, ttk

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageTk
from tkinterdnd2 import DND_FILES

from catalog import IMAGE_SUFFIXES
from desktop_notice import CompletionNotice
from desktop_theme import (
    APPEARANCES, BODY, DARK, DETAIL, FONT, LIGHT, SECTION, TITLE, DesktopStyles, desktop_animation_enabled,
    icon, load_appearance, paint_backdrop, rounded_surface, save_appearance, style_caption, system_theme,
)
from format_picker import FormatPicker
from gradient_ascii import ascii_field, ascii_sweep


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
        self.format_picker = self.layout_job = None
        self.sweep_timer = self.sweep_last_frame = None
        self.sweep_phase = .24
        self.motion_enabled = desktop_animation_enabled()
        self.pack(fill="both", expand=True)
        self.create_image(0, 0, anchor="nw", tags="backdrop")
        self.create_image(0, 0, anchor="nw", tags="ascii-sweep", state="hidden")
        self.create_image(0, 0, anchor="nw", tags="toolbar-surface")
        self.create_image(0, 0, anchor="nw", tags="brand")
        self.create_image(0, 0, anchor="nw", tags="path-surface")
        for name in ("results", "query", "match", "results-empty"):
            self.create_image(0, 0, anchor="nw", tags=f"{name}-glyph")
        self.label_widths = {}

        self.label("product", "截图找原稿", size=SECTION, bold=True, anchor="w")
        self.label("title", "用截图找到原稿", size=TITLE, bold=True, anchor="n")
        self.label("subtitle", "在本机比对设计稿、文档和图片", size=BODY, muted=True, anchor="n")
        self.label("scope-heading", "搜索范围", bold=True, anchor="w")
        self.label("scope", app.project_line, muted=True, anchor="w")
        self.label("input-heading", "截图", bold=True, anchor="w")
        self.label("results", "对比结果", size=SECTION, bold=True, anchor="w")
        self.label("summary", app.result_summary, muted=True)
        self.label("progress", app.progress_text, muted=True)
        self.label("status", app.status, muted=True)
        self.label("query", "客户截图", size=SECTION, bold=True, anchor="w")
        self.label("match", "原稿预览", size=SECTION, bold=True, anchor="w")
        self.label("evidence", app.evidence_line, muted=True)
        self.label("location", app.location_label)

        for name, text, command, glyph in (
            ("open", "选择文件夹…", app.choose_project, "folder"),
            ("demo", "试用样例", app.open_demo, None),
            ("formats", "搜索格式", self.open_search_formats, "chevron"),
            ("paste", "粘贴截图", app.paste_query, "clipboard"),
            ("search", "选择截图…", app.choose_query, "picture"),
            ("clear", "清除", app.clear_query, None),
            ("compare", "开始对比", app.start_compare, "search"),
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
        app.buttons["formats"].configure(compound="right")
        app.progress = ProgressMeter(self, app.progress_value)
        app.rows = {}
        app.tree = ttk.Treeview(self, columns=("match",), show="tree", selectmode="browse",
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
        app.evidence_line.trace_add("write", self.update_path)
        app.progress_text.trace_add("write", lambda *_: self.update_progress())

        self.window_icon = ImageTk.PhotoImage(icon("crop", "#2158a8", self.styles.px(32)), master=root)
        root.iconphoto(True, self.window_icon)
        self.refresh_theme()
        self.bind("<Configure>", self.schedule_layout)
        for event in ("<Map>", "<Unmap>"):
            self.bind(event, lambda _: self.after_idle(self.sync_sweep_timer), add="+")
        root.bind("<Map>", self.on_map, add="+")
        root.bind("<ButtonPress-1>", self.close_formats_on_outside_click, add="+")
        root.bind("<Escape>", self.close_search_formats, add="+")
        root.after(1000, self.follow_system_theme)

    def label(self, name, text, *, size=DETAIL, bold=False, muted=False, anchor="nw"):
        font = tkfont.Font(root=self, family=FONT, size=self.styles.px(size), weight="bold" if bold else "normal")
        item = self.create_text(0, 0, anchor=anchor, font=font, tags=name, justify="left")
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
        self.motion_enabled = desktop_animation_enabled()
        self.sync_sweep_timer()
        self.after(1000, self.follow_system_theme)

    def appearance_label(self):
        return f"外观 · {APPEARANCES[self.appearance.get()]}"

    def open_appearance(self):
        button = self.app.buttons["appearance"]
        try:
            self.appearance_menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            self.appearance_menu.grab_release()

    def listed_suffixes(self):
        return {suffix for _, fields in self.app.format_groups for group in fields.values() for suffix in group}

    def prepare_format_picker(self):
        if self.format_picker is None:
            self.format_picker = FormatPicker(self)

    def open_search_formats(self):
        self.prepare_format_picker()
        if self.format_picker.opened:
            self.format_picker.close()
        else:
            self.format_picker.open()

    def close_search_formats(self, _event=None):
        if self.format_picker and self.format_picker.opened:
            self.format_picker.close()
            return "break"

    def close_formats_on_outside_click(self, event):
        picker = self.format_picker
        widget = event.widget
        if not picker or not picker.opened or widget is self.app.buttons["formats"]:
            return
        while widget is not None:
            if widget is picker:
                return
            widget = getattr(widget, "master", None)
        picker.close(restore_focus=False)

    def select_appearance(self):
        save_appearance(self.appearance.get())
        self.app.buttons["appearance"].configure(text=self.appearance_label())
        self.refresh_theme()

    def refresh_theme(self):
        mode = self.appearance.get()
        palette = system_theme() if mode == "system" else DARK if mode == "dark" else LIGHT
        if palette != self.palette:
            self.apply_theme(palette)

    def apply_theme(self, palette):
        if self.format_picker is not None:
            self.format_picker.close(restore_focus=False)
            self.format_picker.destroy()
            self.format_picker = None
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
            color = "#ffffff" if name == "compare" else palette.muted
            size = self.styles.px(14) if glyph == "chevron" else small_icon
            photo = self.photo(f"icon-{name}", icon(glyph, color, size, centered=True))
            disabled = self.photo(f"icon-{name}-disabled", icon(glyph, palette.disabled, size, centered=True))
            self.app.buttons[name].configure(image=(photo, "disabled", disabled))
        px = self.styles.px
        brand = rounded_surface((px(30), px(30)), palette.primary, px(9))
        brand.alpha_composite(icon("crop", "#ffffff", px(18)), (px(6), px(6)))
        self.itemconfigure("brand", image=self.photo("brand", brand))
        for name, glyph in (("results", "search"), ("query", "picture"), ("match", "match")):
            tag = f"{name}-glyph"
            self.itemconfigure(tag, image=self.photo(tag, icon(glyph, palette.accent, px(17), centered=True)))
        empty = rounded_surface((px(50), px(50)), palette.preview, px(15))
        empty.alpha_composite(icon("search", palette.muted, px(22)), (px(14), px(14)))
        self.itemconfigure("results-empty-glyph", image=self.photo("results-empty-glyph", empty))
        self.file_icons = {
            kind: self.photo(f"file-{kind}", icon(kind, palette.muted, small_icon))
            for kind in ("ps", "ai", "pdf", "raster", "file")
        }
        for row, record in self.app.rows.items():
            self.app.tree.item(row, image=self.file_icon(Path(record.export)))
        self.layout()
        self.after_idle(self.prepare_format_picker)

    def file_icon(self, path):
        suffix = path.suffix.lower()
        formats = {".psd": "ps", ".psb": "ps", ".ai": "ai", ".pdf": "pdf", ".svg": "file"}
        return self.file_icons[formats.get(suffix, "raster" if suffix in IMAGE_SUFFIXES else "file")]

    def photo(self, name, image):
        photo = ImageTk.PhotoImage(image, master=self)
        self.pictures[name] = photo
        return photo

    def schedule_layout(self, _event):
        if self.layout_job is not None:
            self.after_cancel(self.layout_job)
        self.layout_job = self.after(60, self.layout)

    def layout(self):
        if self.layout_job is not None:
            self.after_cancel(self.layout_job)
        self.layout_job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 200 or h < 200:
            return
        p = self.palette
        px = self.styles.px
        button_width = lambda name: self.styles.button_size(name)[0]
        left = max(px(24), (w - px(1340)) // 2)
        right = w - left
        gap = px(14)
        result_width = min(px(340), max(px(242), (right - left) * 27 // 100))
        middle = left + result_width + gap
        right_width = right - middle
        footer = h - px(48)
        compact = h < px(650)
        header_offset = px(18) if compact else 0
        card_top, card_bottom = px(308) - header_offset, footer - px(28)
        preview_top = card_top + px(48)
        preview_width = (right_width - gap) // 2
        right_preview = middle + preview_width + gap
        match_width = right - right_preview
        toolbar_top = px(156) - header_offset
        toolbar_height = px(96)
        inside = left + px(16)
        divider = inside + px(273)
        input_left = divider + px(16)
        action_y = toolbar_top + px(41)
        compare_left = right - px(16) - button_width("compare")

        self.background = background = paint_backdrop(p, (w, h), px)
        field_top = px(56)
        cell = px(14)
        field = ascii_field(w, toolbar_top + toolbar_height - field_top, cell, toolbar_top - field_top, p.dark)
        background.paste(field, (0, field_top), field)
        toolbar_size = (right - left, toolbar_height)
        shadow = rounded_surface(toolbar_size, (6, 18, 50, 9) if not p.dark else (0, 0, 0, 25), px(18))
        background.paste(shadow, (left, toolbar_top + px(4)), shadow)
        for x, width in ((left, result_width), (middle, preview_width), (right_preview, match_width)):
            self.paint_card(background, x, card_top, width, card_bottom - card_top)
        self.itemconfigure("backdrop", image=self.photo("backdrop", background))
        self.sweep_mask = ascii_sweep(cell)
        sweep_start = max(0, toolbar_top - px(53) - field_top)
        self.sweep_band = field.crop((0, sweep_start, w, sweep_start + self.sweep_mask.height))
        self.sweep_y = field_top + sweep_start
        self.sweep_x = None
        self.itemconfigure("ascii-sweep", image=self.photo("ascii-sweep", Image.new("RGBA", self.sweep_mask.size)))
        self.sync_sweep_timer()
        toolbar_fill = (*ImageColor.getrgb(p.panel), 224 if p.dark else 226)
        toolbar = rounded_surface(toolbar_size, toolbar_fill, px(18), edge=p.panel_edge)
        ImageDraw.Draw(toolbar).line((divider - left, px(14), divider - left, toolbar_height - px(14)), fill=p.panel_edge)
        self.coords("toolbar-surface", left, toolbar_top)
        self.itemconfigure("toolbar-surface", image=self.photo("toolbar-surface", toolbar))
        background.paste(toolbar, (left, toolbar_top), toolbar)
        self.coords("brand", left, px(13))
        self.coords("product", left + px(40), px(28))
        self.coords("title", w // 2, px(71 if compact else 76))
        self.coords("subtitle", w // 2, px(116 if compact else 124))
        self.place_buttons(background, ("demo", "appearance"),
                           right - button_width("demo") - button_width("appearance") - px(5), px(11), gap=px(5))

        self.coords("scope-heading", inside, toolbar_top + px(24))
        self.coords("scope", inside + px(69), toolbar_top + px(24))
        self.fit_label("scope", self.app.project_line.get(), divider - inside - px(86))
        self.coords("input-heading", input_left, toolbar_top + px(24))
        self.place_buttons(background, ("open", "formats"), inside, action_y, gap=px(8))
        self.place_buttons(background, ("paste", "search", "clear"), input_left, action_y, gap=px(8))
        self.place_buttons(background, ("compare",), compare_left, action_y, gap=0)

        for name, x in (("results", left), ("query", middle), ("match", right_preview)):
            heading_y = card_top + px(24)
            self.coords(name, x + px(40), heading_y)
            self.coords(f"{name}-glyph", x + px(16), heading_y - px(17) // 2)
        results_middle = (card_top + card_bottom) // 2 + px(14)
        self.coords("results-empty-glyph", left + (result_width - px(50)) // 2, results_middle - px(41))
        self.summary_locations = ((left + result_width // 2, results_middle + px(17)),
                                  (left + px(16), card_top + px(40)))
        self.fit_label("summary", self.app.result_summary.get(), result_width - px(32))
        tree_top = card_top + px(66)
        self.tree_box = dict(x=left + px(11), y=tree_top, width=result_width - px(24),
                             height=card_bottom - tree_top - px(12))
        self.scroll_box = dict(x=left + result_width - px(10), y=tree_top, width=px(4),
                               height=card_bottom - tree_top - px(12))
        status_width = self.app.tree.column("match", "width")
        self.app.tree.column("#0", width=self.tree_box["width"] - status_width)
        self.update_results()

        status_y = px(269) - header_offset
        self.coords("status", left + px(2), status_y)
        self.cancel_position = (right - button_width("cancel"), px(263) - header_offset)
        progress_label_width = px(139)
        progress_width = px(152)
        progress_left = right - progress_label_width - progress_width - px(9)
        progress_y, progress_h = px(278) - header_offset, px(6)
        self.progress_shift = button_width("cancel") + px(8)
        self.status_width = right - left - px(4)
        self.progress_box = dict(x=progress_left, y=progress_y, width=progress_width, height=progress_h)
        area = background.crop((progress_left, progress_y, progress_left + progress_width, progress_y + progress_h))
        self.app.progress.decorate(area.convert("RGBA"), p)
        self.progress_label = (progress_left + progress_width + px(9), status_y)
        self.fit_label("progress", self.app.progress_text.get(), progress_label_width)
        self.update_progress()

        inset = px(9)
        preview_height = card_bottom - preview_top - inset
        for left_edge, width, preview in ((middle, preview_width, self.app.query_preview),
                                          (right_preview, match_width, self.app.match_preview)):
            x = left_edge + inset
            width -= 2 * inset
            area = Image.new("RGBA", (width, preview_height), p.panel)
            area.alpha_composite(rounded_surface(area.size, p.preview, px(12)))
            preview.decorate(area, p)
            preview.place(x=x, y=preview_top, width=width, height=preview_height)

        self.coords("location", middle, footer - px(21))
        self.coords("evidence", middle + px(121), footer - px(21))
        self.fit_label("evidence", self.app.evidence_line.get(), right_width - px(121))
        button_left = right - button_width("remember") - button_width("reveal") - px(8)
        path_width = button_left - px(8) - middle
        self.coords("path-surface", middle, footer)
        self.itemconfigure("path-surface", image=self.photo("path-surface", rounded_surface(
            (path_width, px(36)), p.panel, px(8), edge=p.panel_edge)))
        self.path_box = dict(x=middle + px(8), y=footer + px(4), width=path_width - px(16), height=px(28))
        self.path_buttons = (button_left, footer)
        self.update_path()
        if self.format_picker is not None:
            self.format_picker.reposition()

    def paint_card(self, background, x, y, width, height):
        panel = rounded_surface((width, height), self.palette.panel, self.styles.px(18), edge=self.palette.panel_edge)
        background.paste(panel, (x, y), panel)

    def position_sweep(self):
        width, height = self.sweep_mask.size
        x = round(self.sweep_phase * (self.sweep_band.width + width)) - width
        if x == self.sweep_x:
            return
        self.sweep_x = x
        sprite = self.sweep_band.crop((x, 0, x + width, height))
        sprite.putalpha(ImageChops.multiply(sprite.getchannel("A"), self.sweep_mask))
        self.pictures["ascii-sweep"].paste(sprite)
        self.coords("ascii-sweep", x, self.sweep_y)

    def sweep_is_active(self):
        return ("ascii-sweep" in self.pictures and self.motion_enabled and self.winfo_viewable()
                and self.app.root.state() in ("normal", "zoomed"))

    def sync_sweep_timer(self):
        active = self.sweep_is_active()
        state = "normal" if active else "hidden"
        if self.itemcget("ascii-sweep", "state") != state:
            self.itemconfigure("ascii-sweep", state=state)
        if active:
            self.position_sweep()
            if self.sweep_timer is None:
                self.sweep_timer = self.after(33, self.tick_sweep)
            return
        if self.sweep_timer is not None:
            self.after_cancel(self.sweep_timer)
            self.sweep_timer = None
        self.sweep_last_frame = None

    def tick_sweep(self):
        self.sweep_timer = None
        if not self.sweep_is_active():
            self.sync_sweep_timer()
            return
        now = monotonic()
        elapsed = min(.12, now - self.sweep_last_frame) if self.sweep_last_frame is not None else .033
        self.sweep_last_frame = now
        self.sweep_phase = (self.sweep_phase + elapsed / 4.3) % 1
        self.position_sweep()
        menu_open = self.format_picker is not None and self.format_picker.opened
        self.sweep_timer = self.after(90 if self.app.busy or menu_open else 33, self.tick_sweep)

    def set_scroll(self, first, last):
        self.scroll.set(first, last)
        if hasattr(self, "scroll_box") and self.app.rows and (float(first) > 0 or float(last) < 1):
            self.scroll.place(**self.scroll_box)
        else:
            self.scroll.place_forget()

    def update_results(self):
        if not hasattr(self, "tree_box"):
            return
        filled = bool(self.app.rows)
        self.itemconfigure("results-empty-glyph", state="hidden" if filled else "normal")
        self.itemconfigure("summary", anchor="nw" if filled else "n")
        self.coords("summary", *self.summary_locations[filled])
        if filled:
            self.app.tree.place(**self.tree_box)
        else:
            self.app.tree.place_forget()
        self.set_scroll(*self.app.tree.yview())

    def update_progress(self):
        if not hasattr(self, "progress_box"):
            return
        active = self.app.progress_text.get() != "等待开始"
        shift = self.progress_shift if self.app.comparing else 0
        self.itemconfigure("status", width=self.status_width if not active else
                           self.progress_box["x"] - shift - self.coords("status")[0] - self.styles.px(12))
        self.coords("progress", self.progress_label[0] - shift, self.progress_label[1])
        self.itemconfigure("progress", state="normal" if active else "hidden")
        if active:
            self.app.progress.place(**(self.progress_box | {"x": self.progress_box["x"] - shift}))
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
        self.itemconfigure("evidence", state="normal" if self.app.evidence_line.get() else "hidden")
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
