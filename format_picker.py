"""Anchored file-format picker with a gliding highlight and multiple selection."""

import tkinter as tk
from time import monotonic
from tkinter import ttk

from PIL import Image, ImageTk

from catalog import parse_suffixes
from desktop_theme import DETAIL, FONT, icon, rounded_surface


class FormatPicker(tk.Frame):
    def __init__(self, view):
        self.view = view
        self.app = view.app
        self.px = px = view.styles.px
        self.palette = p = view.palette
        super().__init__(view, background=p.panel_edge)
        self.trigger = self.app.buttons["formats"]
        self.selected = set()
        self.opened = False
        self.groups = self.app.format_groups
        self.rows = []
        self.active = 0
        self.slide = self.pop = None
        self.row_height = px(29)
        self.list_width = px(321)
        self.pill_y = 0
        self.tick = ImageTk.PhotoImage(icon("tick", p.accent, px(17)), master=self)
        pill = rounded_surface((self.list_width - px(4), self.row_height - px(2)), p.selected, px(9))
        self.highlight = ImageTk.PhotoImage(pill, master=self)
        frame = tk.Frame(self, background=p.panel, padx=px(10), pady=px(9))
        frame.pack(padx=1, pady=1, fill="both", expand=True)
        tabs = tk.Frame(frame, background=p.panel)
        tabs.pack(fill="x", pady=(0, px(6)))
        self.tabs = []
        for index, (label, _) in enumerate(self.groups):
            button = tk.Button(tabs, text=label, font=(FONT, px(DETAIL)), relief="flat", borderwidth=0,
                               foreground=p.text, activebackground=p.hover, activeforeground=p.text,
                               highlightthickness=1, highlightbackground=p.panel, highlightcolor=p.accent,
                               command=lambda group=index: self.show_group(group))
            tabs.columnconfigure(index, weight=1, uniform="format-tabs")
            button.grid(row=0, column=index, sticky="ew", padx=px(2), ipady=px(2))
            self.tabs.append(button)

        row_count = max(len(fields) for _, fields in self.groups)
        self.options = tk.Canvas(frame, width=self.list_width, height=self.row_height * row_count,
                                 background=p.panel, highlightthickness=0, takefocus=True)
        self.options.pack(fill="x")
        self.options.bind("<Motion>", self.on_motion)
        self.options.bind("<Button-1>", self.on_click)
        for key, offset in (("Up", -1), ("Down", 1)):
            self.options.bind(f"<{key}>", lambda _, step=offset: self.move_selection(step))
        self.options.bind("<space>", self.toggle_active)
        self.options.bind("<Return>", self.toggle_active)
        tk.Frame(frame, height=1, background=p.panel_edge).pack(fill="x", pady=(px(5), px(7)))

        self.custom = tk.StringVar(self)
        self.keyword = tk.StringVar(self)
        fields = tk.Frame(frame, background=p.panel)
        fields.pack(fill="x")
        for row, (name, variable) in enumerate((("其他后缀", self.custom), ("文件名 / TXT 关键词", self.keyword))):
            tk.Label(fields, text=name, font=(FONT, px(-12)), background=p.panel,
                     foreground=p.muted, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, px(7)))
            field = ttk.Entry(fields, textvariable=variable, style="Filter.TEntry", width=18)
            field.grid(row=row, column=1, sticky="ew", pady=px(2))
            field.bind("<Return>", lambda _: self.apply_selection())
            if row == 0:
                self.custom_entry = field
        fields.columnconfigure(1, weight=1)

        self.error = tk.StringVar(self)
        self.error_label = tk.Label(frame, textvariable=self.error, background=p.panel, foreground=p.text,
                                    font=(FONT, px(-12)), wraplength=self.list_width, justify="left", anchor="w")
        actions = tk.Frame(frame, background=p.panel)
        self.actions = actions
        actions.pack(fill="x", pady=(px(5), 0))
        for name, label, command in (("format_apply", "应用", self.apply_selection), ("format_cancel", "取消", self.close)):
            size = view.styles.button_size(name)
            view.styles.draw_button(name, p, Image.new("RGBA", size, p.panel))
            ttk.Button(actions, text=label, style=view.styles.button_style(name), command=command).pack(
                side="right", padx=(px(5), 0))
        self.count = tk.StringVar(self)
        tk.Label(actions, textvariable=self.count, background=p.panel, foreground=p.muted,
                 font=(FONT, px(-12))).pack(side="left")
        self.custom.trace_add("write", lambda *_: self.update_count())
        self.show_group(0)

    def open(self):
        self.selected = set(self.app.active_suffixes)
        self.custom.set(", ".join(sorted(self.selected - self.view.listed_suffixes())))
        self.keyword.set(self.app.active_keyword)
        self.error.set("")
        self.error_label.pack_forget()
        initial_group = max(range(len(self.groups)),
                            key=lambda i: sum(bool(self.selected.intersection(group)) for group in self.groups[i][1].values()))
        self.show_group(initial_group)
        self.opened = True
        x, y = self.position()
        self.place(x=x, y=y)
        self.lift()
        self.options.focus_set()
        if self.view.motion_enabled:
            self.play_open(x, y)

    def play_open(self, x, y):
        start = monotonic()

        def frame():
            fraction = min(1, (monotonic() - start) / .095)
            self.place_configure(x=x, y=y - round(self.px(5) * (1 - fraction)**3))
            self.pop = self.after(15, frame) if fraction < 1 else None

        frame()

    def position(self):
        px = self.px
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        x = max(px(8), min(self.trigger.winfo_x(), self.view.winfo_width() - width - px(8)))
        below = self.trigger.winfo_y() + self.trigger.winfo_height() + px(7)
        above = self.trigger.winfo_y() - height - px(7)
        bottom = self.view.winfo_height() - px(8)
        y = below if below + height <= bottom else max(px(8), above, min(below, bottom - height))
        return x, y

    def reposition(self):
        if self.opened and self.pop is None:
            x, y = self.position()
            self.place_configure(x=x, y=y)
            self.lift()

    def show_group(self, index):
        self.rows = list(self.groups[index][1].items())
        for position, tab in enumerate(self.tabs):
            chosen = position == index
            tab.configure(background=self.palette.selected if chosen else self.palette.panel,
                          foreground=self.palette.accent if chosen else self.palette.text)
        self.options.delete("all")
        self.active = next((i for i, (_, suffixes) in enumerate(self.rows)
                            if self.selected.intersection(suffixes)), 0)
        self.options.create_image(self.px(2), self.active * self.row_height, anchor="nw",
                                  image=self.highlight, tags="pill")
        for index, (label, _) in enumerate(self.rows):
            center = index * self.row_height + self.row_height // 2
            self.options.create_text(self.px(12), center, anchor="w", text=label,
                                     font=(FONT, self.px(DETAIL)), fill=self.palette.text)
            self.options.create_image(self.list_width - self.px(17), center, image=self.tick, tags=f"check-{index}")
        self.move_pill(self.active, animate=False)
        self.update_checks()
        self.update_count()

    def move_pill(self, index, *, animate=True):
        if self.slide is not None:
            self.after_cancel(self.slide)
            self.slide = None
        target = index * self.row_height
        start = self.pill_y
        if not animate or not self.view.motion_enabled or start == target:
            self.pill_y = target
            self.options.coords("pill", self.px(2), target)
            return
        begin = monotonic()

        def frame():
            fraction = min(1, (monotonic() - begin) / .20)
            self.pill_y = start + (target - start) * (1 - (1 - fraction)**3)
            self.options.coords("pill", self.px(2), self.pill_y)
            self.slide = self.after(15, frame) if fraction < 1 else None

        frame()

    def activate(self, index):
        if index != self.active and 0 <= index < len(self.rows):
            self.active = index
            self.move_pill(index)

    def on_motion(self, event):
        self.activate(event.y // self.row_height)

    def on_click(self, event):
        index = event.y // self.row_height
        if 0 <= index < len(self.rows):
            self.options.focus_set()
            self.activate(index)
            self.toggle_active()
        return "break"

    def move_selection(self, step):
        self.activate((self.active + step) % len(self.rows))
        return "break"

    def toggle_active(self, _event=None):
        _, suffixes = self.rows[self.active]
        if self.selected.intersection(suffixes):
            self.selected.difference_update(suffixes)
        else:
            self.selected.update(suffixes)
        self.update_checks()
        self.update_count()
        return "break"

    def update_checks(self):
        for index, (_, suffixes) in enumerate(self.rows):
            state = "normal" if self.selected.intersection(suffixes) else "hidden"
            self.options.itemconfigure(f"check-{index}", state=state)

    def update_count(self):
        try:
            chosen = self.selected | parse_suffixes(self.custom.get())
        except ValueError:
            chosen = self.selected
        count = sum(bool(chosen.intersection(suffixes)) for _, fields in self.groups for suffixes in fields.values())
        count += len(chosen - self.view.listed_suffixes())
        self.count.set(f"已选 {count} 项")

    def apply_selection(self):
        try:
            additional = parse_suffixes(self.custom.get())
        except ValueError as problem:
            self.error.set(str(problem))
            self.error_label.pack(fill="x", before=self.actions)
            self.after_idle(self.reposition)
            self.custom_entry.focus_set()
            return "break"
        self.app.set_search_formats((self.selected & self.view.listed_suffixes()) | additional, self.keyword.get())
        self.close()
        return "break"

    def close(self, *, restore_focus=True):
        for job in (self.slide, self.pop):
            if job is not None:
                self.after_cancel(job)
        self.slide = self.pop = None
        self.opened = False
        self.place_forget()
        if restore_focus:
            self.trigger.focus_set()
