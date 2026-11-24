"""A non-modal search-completion notice."""

import os
import sys
import tkinter as tk
from pathlib import Path

from desktop_theme import BODY, DETAIL, FONT
from windows_shell import show_corner_window


def play_completion_sound():
    if sys.platform != "win32":
        return
    import winsound

    media = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Media"
    chime = media / "Windows Notify System Generic.wav"
    try:
        winsound.PlaySound(str(chime), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError:
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except RuntimeError:
            pass


class CompletionNotice:
    def __init__(self, root, px):
        self.root = root
        self.px = px
        self.window = self.timeout = None

    def show(self, count, palette):
        if self.root.state() == "withdrawn":
            return
        self.dismiss()
        px = self.px
        toast = tk.Toplevel(self.root)
        self.window = toast
        toast.withdraw()
        toast.overrideredirect(True)
        toast.configure(background=palette.panel, highlightbackground=palette.panel_edge, highlightthickness=1,
                        cursor="hand2")
        width, height = px(320), px(108)
        surface = tk.Canvas(toast, background=palette.panel, highlightthickness=0, cursor="hand2")
        surface.pack(fill="both", expand=True)
        surface.create_rectangle(0, 0, px(4), height, fill=palette.primary, width=0)
        surface.create_text(px(20), px(16), text="截图找原稿 · 对比完成", anchor="nw",
                            font=(FONT, px(BODY), "bold"), fill=palette.text)
        summary = f"找到 {count} 个候选文件" if count else "没有找到匹配文件"
        surface.create_text(px(20), px(44), text=summary, anchor="nw",
                            font=(FONT, px(DETAIL)), fill=palette.muted)
        surface.create_text(px(20), px(75), text="查看结果", anchor="nw",
                            font=(FONT, px(DETAIL)), fill=palette.accent)
        surface.bind("<Button-1>", self.return_to_results)
        if sys.platform == "win32":
            show_corner_window(toast, self.root, width, height, px(16))
        else:
            toast.geometry(f"{width}x{height}-16-48")
            toast.attributes("-topmost", True)
            toast.deiconify()
        self.timeout = self.root.after(8500, self.dismiss)
        if count:
            play_completion_sound()

    def dismiss(self):
        if self.timeout is not None:
            self.root.after_cancel(self.timeout)
            self.timeout = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def return_to_results(self, _event):
        self.dismiss()
        if self.root.state() == "iconic":
            self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
