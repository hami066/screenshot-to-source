"""Offline desktop application for Screenshot to Source."""

import queue
import sqlite3
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageDraw, ImageOps, ImageTk
from tkinterdnd2 import TkinterDnD

from catalog import IMAGE_SUFFIXES, IMAGE_TYPES, Catalog, Record, matches_keyword, scan_exports, text_key
from clipboard_image import ClipboardImageError, read_clipboard_image
from desktop_theme import BODY, DETAIL, FONT, display_scale, enable_windows_dpi, icon, rounded_surface
from desktop_view import DesktopView
from design_preview import ARCHIVE_ENTRIES, DOCUMENT_SUFFIXES, PHOTOSHOP_SUFFIXES
from local_paths import project_file
from matcher import Matcher, normalize_image, read_image, read_reference
from windows_shell import reveal_file

APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) and sys.platform == "win32" else __file__).resolve().parent
DEMO_DIR = (APP_DIR / "demo").resolve()
IMAGE_PICKER = [("图片", " ".join(f"*{suffix}" for suffix in sorted(IMAGE_SUFFIXES)))]
ORIGINAL_SUFFIXES = DOCUMENT_SUFFIXES - {".pdf"}
PREVIEW_SUFFIXES = DOCUMENT_SUFFIXES | IMAGE_SUFFIXES
DEFAULT_SUFFIXES = frozenset({".psd", ".psb", ".ai", ".pdf"})
FORMAT_GROUPS = (
    ("设计原稿", {"PSD": (".psd",), "PSB": (".psb",), "AI": (".ai",), "Sketch": (".sketch",), "Figma": (".fig",)}),
    ("办公文件", {"PDF": (".pdf",), "PPTX": (".pptx",), "DOCX": (".docx",), "XLSX": (".xlsx",), "TXT": (".txt",)}),
    ("图片", IMAGE_TYPES),
)
PASTE_SHORTCUT = "⌘ V" if sys.platform == "darwin" else "Ctrl+V"
SUFFIX_RESULT_LIMIT = 500
DISPLAY_IMAGE_EDGE = 2400


class Preview(tk.Canvas):
    def __init__(self, parent, hint, *, query=False):
        super().__init__(parent, highlightthickness=0, borderwidth=0)
        self.hint = hint
        self.px = parent.styles.px
        self.image = self.photo = self.surface = self.empty_icon = None
        self.query = query
        self.bind("<Configure>", self.paint)

    def decorate(self, surface, palette):
        self.surface = ImageTk.PhotoImage(surface, master=self)
        self.palette = palette
        size = self.px(50)
        tile = rounded_surface((size, size), palette.panel, self.px(15), edge=palette.panel_edge)
        glyph = icon("crop" if self.query else "file", palette.accent if self.query else palette.muted, self.px(22))
        tile.alpha_composite(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2))
        self.empty_icon = ImageTk.PhotoImage(tile, master=self)
        self.paint()

    def set(self, image=None, box=None):
        self.image = None
        if image:
            original = image
            if max(image.size) > DISPLAY_IMAGE_EDGE:
                image = ImageOps.contain(image, (DISPLAY_IMAGE_EDGE, DISPLAY_IMAGE_EDGE), Image.Resampling.LANCZOS)
            if box:
                if image is original:
                    image = image.copy()
                sx, sy = image.width / original.width, image.height / original.height
                coordinates = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(box))
                draw = ImageDraw.Draw(image)
                draw.rectangle(coordinates, outline="#141b23", width=5)
                draw.rectangle(coordinates, outline="#fddd56", width=3)
            self.image = image
        self.paint()

    def paint(self, _event=None):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if min(width, height) < 20:
            return
        if self.surface:
            self.create_image(0, 0, image=self.surface, anchor="nw")
        if self.image is None:
            self.photo = None
            if self.empty_icon:
                self.paint_empty(width / 2, height / 2)
            return
        image = self.image.copy()
        inset = self.px(20)
        image.thumbnail((max(1, width - inset), max(1, height - inset)), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.create_image(width / 2, height / 2, image=self.photo)

    def paint_empty(self, x, y):
        palette = self.palette
        px = self.px
        self.create_image(x, y - px(20 if self.query else 14), image=self.empty_icon)
        self.create_text(x, y + px(17 if self.query else 26), text=self.hint, fill=palette.text,
                         width=max(px(80), self.winfo_width() - px(24)), justify="center", font=(FONT, px(BODY)))
        if self.query:
            self.create_text(x, y + px(40), text=PASTE_SHORTCUT, fill=palette.muted, font=(FONT, px(DETAIL)))


class App:
    def __init__(self, root):
        self.root = root
        self.catalog = self.matcher = self.cancel = None
        self.results = {}
        self.events = queue.Queue()
        self.jobs = queue.Queue(maxsize=1)
        self.request = 0
        self.busy = False
        self.query_image = self.query_path = None
        self.comparing = False
        self.is_demo = False
        self.search_suffixes = DEFAULT_SUFFIXES
        self.demo_suffixes = frozenset({".png"})
        self.file_keyword = self.demo_keyword = ""
        self.format_groups = FORMAT_GROUPS
        self.project_line = tk.StringVar(value="尚未选择文件夹")
        self.status = tk.StringVar(value="粘贴截图后，点击「开始对比」")
        self.progress_value = tk.IntVar(value=0)
        self.progress_text = tk.StringVar(value="等待开始")
        self.location_path = tk.StringVar()
        self.location_label = tk.StringVar(value="图片与原稿位置")
        self.evidence_line = tk.StringVar()
        self.result_summary = tk.StringVar(value="暂无候选文件")
        self.selected_location = None
        self.buttons = {}
        self.setup()
        modifier = "Command" if sys.platform == "darwin" else "Control"
        for shortcut in (f"<{modifier}-KeyPress-v>", f"<{modifier}-KeyPress-V>"):
            root.bind_class("ScreenshotPaste", shortcut, self.paste_query)
        self.bind_paste(root)
        threading.Thread(target=self.run_searches, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)

    def bind_paste(self, widget):
        widget.bindtags(("ScreenshotPaste", *widget.bindtags()))
        for child in widget.winfo_children():
            self.bind_paste(child)

    def setup(self):
        root = self.root
        root.title("截图找原稿 · Screenshot to Source")
        scale = display_scale(root)
        width = min(round(1120 * scale), max(round(945 * scale), root.winfo_screenwidth() - round(48 * scale)))
        height = min(round(720 * scale), max(round(610 * scale), root.winfo_screenheight() - round(88 * scale)))
        root.geometry(f"{width}x{height}")
        root.minsize(round(945 * scale), round(610 * scale))
        self.view = DesktopView(self, Preview)
        self.sync_buttons()

    def sync_buttons(self):
        for name, button in self.buttons.items():
            enabled = not self.busy
            if name in ("paste", "search", "appearance"):
                enabled = True
            if name == "clear":
                enabled = self.busy or self.query_preview.image is not None
            if name == "cancel":
                enabled = self.comparing
            if name == "remember":
                record = self.selected_record()
                enabled = (enabled and not self.is_demo and record is not None
                           and Path(record.export).suffix.lower() in IMAGE_SUFFIXES | {".pdf"})
            if name == "reveal":
                enabled = enabled and sys.platform in ("win32", "darwin") and self.selected_location is not None
            button.state(["!disabled"] if enabled else ["disabled"])
        start_label = "开始查找" if self.query_image is None and self.active_suffixes - PREVIEW_SUFFIXES else "开始对比"
        compare_label = "正在查找…" if self.comparing else "正在读取截图…" if self.busy else start_label
        self.buttons["compare"].configure(text=compare_label)
        paste_label = "更换截图" if self.query_preview.image is not None else "粘贴截图"
        self.buttons["paste"].configure(text=paste_label)

    def warn(self, message):
        messagebox.showwarning("截图找原稿", message, parent=self.root)

    def choose_project(self):
        path = filedialog.askdirectory(parent=self.root, title="选择存放设计稿的文件夹", mustexist=True)
        return bool(path) and self.open_project(path)

    def open_project(self, path, *, demo=False):
        try:
            catalog = Catalog(path, read_saved=not demo)
        except (OSError, ValueError, sqlite3.Error):
            self.warn("无法打开搜索文件夹。请选择本机磁盘上的目录，并确认它和已有记录可读。")
            return False
        if demo:
            self.demo_suffixes = frozenset({".png"})
            self.demo_keyword = ""
        self.catalog, self.matcher, self.is_demo = catalog, Matcher(), demo
        self.project_line.set("内置样例" if demo else f"{catalog.root}（含子文件夹）")
        self.reset_results()
        self.show_ready_status()
        return True

    def open_demo(self):
        if not self.open_project(DEMO_DIR, demo=True):
            return
        try:
            for version in ("A", "B", "C"):
                self.catalog.add(
                    self.catalog.root / f"导出图 {version}.png",
                    self.catalog.root / f"可编辑原稿 {version}.svg",
                    f"画板 {version}",
                )
            self.load_query(self.catalog.root / "客户截图.jpg")
        except (OSError, ValueError):
            self.warn("样例文件不完整，请保留程序旁边的 demo 目录。")

    def remember_source(self):
        selected = self.tree.selection()
        if not selected:
            return
        record = self.rows[selected[0]]
        source = filedialog.askopenfilename(parent=self.root, initialdir=self.catalog.root,
                                            title="选择这张成品图对应的原稿（例如 PSD、AI）")
        if not source:
            return
        artboard = simpledialog.askstring(
            "记住原稿", "可以填写画板编号，也可以留空。点确定后将关联保存到搜索文件夹。",
            initialvalue=record.artboard, parent=self.root,
        )
        if artboard is None:
            return
        try:
            self.rows[selected[0]] = self.catalog.remember(
                project_file(self.catalog.root, record.export), source, artboard,
            )
        except (OSError, ValueError, sqlite3.Error):
            self.warn("无法记住原稿。请确认原稿在搜索范围内、有权读取，并且搜索文件夹可保存记录。")
            return
        self.select()
        self.status.set("已记住原稿。下次找到这张成品图时，会直接显示原稿位置。")

    def show_ready_status(self):
        if self.active_suffixes - PREVIEW_SUFFIXES and self.query_image is None:
            self.status.set("可直接按后缀查找。粘贴截图后也能比对已勾选的图片或文档。")
            return
        if self.query_image is not None:
            next_step = "点击「开始对比」。" if self.catalog else "点击「开始对比」并选择搜索文件夹。"
            self.status.set("截图已就绪。" + next_step)
        elif self.catalog:
            self.status.set("搜索范围已选好。请粘贴截图，再点击「开始对比」。")
        else:
            self.status.set("先粘贴截图，再点「开始对比」。")

    @property
    def active_suffixes(self):
        return self.demo_suffixes if self.is_demo else self.search_suffixes

    @property
    def active_keyword(self):
        return self.demo_keyword if self.is_demo else self.file_keyword

    def set_search_formats(self, suffixes, keyword=""):
        chosen = frozenset(suffixes)
        keyword = keyword.strip()
        if (chosen, keyword) == (self.active_suffixes, self.active_keyword):
            return
        if self.is_demo:
            self.demo_suffixes = chosen
            self.demo_keyword = keyword
        else:
            self.search_suffixes = chosen
            self.file_keyword = keyword
        self.reset_results()
        self.show_ready_status()

    def reset_results(self):
        self.results = {}
        self.progress.stop()
        self.progress.set_mode("determinate")
        self.progress_value.set(0)
        self.progress_text.set("等待开始")
        self.result_summary.set("暂无候选文件")
        self.fill([])

    def update_progress(self, processed, total):
        if self.progress.mode != "determinate":
            self.progress.set_mode("determinate")
        percent = processed * 100 // total if total else 100
        self.progress_value.set(percent)
        self.progress_text.set(f"{percent}% · {processed}/{total} 份" if total else "扫描完成 · 0 份文件")

    def reset_location(self):
        self.selected_location = None
        self.location_label.set("图片与原稿位置")
        self.location_path.set("")

    def selected_record(self):
        selected = self.tree.selection()
        return self.rows.get(selected[0]) if selected else None

    def fill(self, records):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.reset_location()
        self.evidence_line.set("")
        self.match_preview.hint = "对比后显示匹配画面"
        self.match_preview.set()
        for record in records:
            evidence = self.results[record.export]
            status = "关键词符合" if self.active_keyword else "后缀符合"
            if evidence is not None:
                status = "整图一致" if evidence.exact else "局部匹配"
            if evidence is not None and evidence.page is not None:
                status = f"第 {evidence.page + 1} 页"
            path = Path(record.export)
            row = self.tree.insert("", "end", text=path.name, image=self.view.file_icon(path), values=(status,))
            self.rows[row] = record
        self.view.update_results()
        self.sync_buttons()

    def select(self, _event=None):
        record = self.selected_record()
        if record is None or self.busy:
            return
        self.reset_location()
        self.sync_buttons()
        self.match_preview.set()
        evidence = self.results[record.export]
        try:
            export, source = self.catalog.paths(record)
            image = read_reference(export, evidence.page) if evidence is not None else None
        except (OSError, ValueError, Image.DecompressionBombError):
            self.evidence_line.set("该文件的预览已不可读，请检查文件位置和权限。")
            return
        suffix = export.suffix.lower()
        self.selected_location = "source" if source else "export"
        self.location_path.set(str(source or export))
        if evidence is None:
            self.location_label.set("文件位置")
            self.evidence_line.set("匹配方式 · 后缀及关键词" if self.active_keyword else "匹配方式 · 文件后缀")
            self.match_preview.hint = "此结果按文件后缀找到"
            self.match_preview.paint()
            self.sync_buttons()
            return
        self.match_preview.hint = "对比后显示匹配画面"
        self.match_preview.set(image, evidence.box if not evidence.exact else None)
        detail = "整图像素一致" if evidence.exact else "黄色框标出了截图对应的位置"
        if evidence.page is not None:
            detail += f" · 第 {evidence.page + 1} 页"
        elif suffix in PHOTOSHOP_SUFFIXES:
            detail += " · Photoshop 保存时的合成画面"
        elif suffix in ARCHIVE_ENTRIES:
            detail += " · 文件内嵌缩略图"
        kind = "原稿" if source or suffix in ORIGINAL_SUFFIXES else "PDF" if suffix == ".pdf" else "成品图"
        self.location_label.set(f"{kind}位置")
        if source:
            detail += f" · {record.artboard}" if record.artboard else " · 已关联原稿"
        elif suffix not in ORIGINAL_SUFFIXES:
            detail += "。如要下次找到原稿，请点「记住原稿」。"
        self.evidence_line.set(detail)
        self.sync_buttons()

    def reveal_selected_file(self):
        record = self.selected_record()
        if self.busy or not record or not self.selected_location:
            return
        threading.Thread(target=self.reveal_location, args=(self.request, self.catalog, record, self.selected_location),
                         daemon=True).start()

    def reveal_location(self, request, catalog, record, location):
        try:
            export, source = catalog.paths(record)
            target = source if location == "source" else export
            if target is None:
                raise FileNotFoundError(record.source)
            with target.open("rb"):
                pass
            reveal_file(target)
        except (OSError, ValueError):
            self.events.put((request, "reveal_error", (record, location)))

    def choose_query(self):
        file = filedialog.askopenfilename(parent=self.root, title="选择要查找的截图", filetypes=IMAGE_PICKER)
        if file:
            self.load_query(file)

    def paste_query(self, _event=None):
        try:
            image = read_clipboard_image()
        except ClipboardImageError as error:
            self.status.set(str(error))
            return "break"
        except OSError:
            self.status.set("暂时读不到剪贴板，请重新截图后再粘贴。")
            return "break"
        self.load_query(image)
        return "break"

    def drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if len(files) == 1:
            self.load_query(files[0])
        else:
            self.warn("一次拖入一张截图。")

    def load_query(self, image_or_path):
        self.query_image = self.query_path = None
        self.query_preview.set()
        self.comparing = False
        self.queue_job(self.read_query, image_or_path)
        self.reset_results()
        self.status.set("正在读取截图…")

    def start_compare(self):
        if self.busy:
            return
        if self.query_image is None and self.active_suffixes and not self.active_suffixes - PREVIEW_SUFFIXES:
            self.status.set(f"请先按 {PASTE_SHORTCUT} 粘贴截图，或从文件选择截图。")
            return
        if self.catalog is None:
            self.status.set("请在弹出的窗口里选择要搜索的文件夹。")
            if not self.choose_project():
                self.status.set("还未选择搜索文件夹。点击「开始对比」可以重新选择。")
                return
        suffixes = self.active_suffixes
        if not suffixes:
            self.status.set("请在左侧「搜索格式」里勾选至少一种文件格式。")
            self.buttons["formats"].focus_set()
            return
        if self.query_image is None:
            suffixes = suffixes - PREVIEW_SUFFIXES
            if not suffixes:
                self.status.set(f"请先按 {PASTE_SHORTCUT} 粘贴截图，或从文件选择截图。")
                return
        excluded = {self.query_path}
        if self.is_demo:
            excluded.add(self.catalog.root / "客户截图.jpg")
        self.comparing = True
        self.queue_job(self.compare_files, self.catalog.root, self.catalog.records.copy(),
                       self.matcher, self.query_image, excluded, suffixes, self.active_keyword)
        self.reset_results()
        self.progress.set_mode("indeterminate")
        self.progress.start(32)
        self.progress_text.set("正在扫描文件夹…")
        self.result_summary.set("正在查找，完成后显示候选文件。")
        self.status.set("已开始对比。正在扫描文件夹和子文件夹中所选格式的文件…")

    def queue_job(self, operation, *arguments):
        self.invalidate_search()
        self.busy = True
        self.cancel = threading.Event()
        self.jobs.put_nowait((self.request, self.cancel, operation, arguments))

    def invalidate_search(self):
        if self.cancel is not None:
            self.cancel.set()
        self.request += 1
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass

    def run_searches(self):
        while True:
            self.run_job(*self.jobs.get())

    def run_job(self, request, cancel, operation, arguments):
        def report(event, value=None):
            if cancel.is_set():
                return
            self.events.put((request, event, value))

        if not cancel.is_set():
            try:
                operation(report, cancel, *arguments)
            except Exception:
                report("error")

    @staticmethod
    def read_query(report, cancel, image_or_path):
        path = None if isinstance(image_or_path, Image.Image) else Path(image_or_path)
        screenshot = normalize_image(image_or_path) if path is None else read_image(path)
        if not cancel.is_set():
            preview = screenshot
            if max(screenshot.size) > DISPLAY_IMAGE_EDGE:
                preview = ImageOps.contain(screenshot, (DISPLAY_IMAGE_EDGE, DISPLAY_IMAGE_EDGE), Image.Resampling.LANCZOS)
            report("loaded", (screenshot, preview, path))

    @staticmethod
    def compare_files(report, cancel, root, saved, matcher, screenshot, excluded, suffixes, keyword=""):
        exports, inaccessible = scan_exports(
            root, excluded, cancel.is_set,
            lambda count: report("scanning", count),
            suffixes=suffixes, prioritize=DOCUMENT_SUFFIXES,
        )
        if cancel.is_set():
            return
        matches, by_suffix = [], []
        compared = suffix_count = 0
        total = len(exports)
        if total:
            report("progress", (0, total, 0))
            query = matcher.query(screenshot) if screenshot is not None and suffixes & PREVIEW_SUFFIXES else None
            keyword = text_key(keyword)
            for index, relative in enumerate(exports, 1):
                if cancel.is_set():
                    return
                try:
                    path = project_file(root, relative)
                    if path.suffix.lower() in PREVIEW_SUFFIXES:
                        evidence = matcher.match(query, path, cancelled=cancel.is_set)
                        compared += 1
                        if evidence:
                            matches.append((saved.get(relative) or Record(relative), evidence))
                    elif matches_keyword(path, keyword):
                        suffix_count += 1
                        if len(by_suffix) < SUFFIX_RESULT_LIMIT:
                            by_suffix.append((Record(relative), None))
                except (OSError, ValueError, Image.DecompressionBombError):
                    inaccessible += 1
                if total <= 100 or index % 4 == 0 or index == total:
                    report("progress", (index, total, len(matches) + suffix_count))
        matches.sort(key=lambda pair: (not pair[1].exact, -pair[1].inliers, -pair[1].ratio, pair[0].export))
        report("results", (matches + by_suffix, compared, inaccessible, total, suffix_count))

    def cancel_compare(self):
        self.invalidate_search()
        self.comparing = self.busy = False
        self.reset_results()
        self.progress_text.set("对比已取消")
        self.status.set("对比已取消。截图仍在，可以再次点击「开始对比」。")

    def clear_query(self):
        self.invalidate_search()
        self.comparing = self.busy = False
        self.query_image = self.query_path = None
        self.query_preview.set()
        self.reset_results()
        self.status.set("截图已清除。可以粘贴或选择另一张截图。")

    def poll(self):
        while True:
            try:
                request, event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if request != self.request:
                continue
            if event == "scanning":
                self.progress_text.set(f"扫描中 · 已找到 {value} 份")
            elif event == "reveal_error":
                if value == (self.selected_record(), self.selected_location):
                    self.status.set("无法定位文件，请确认文件仍在原位置并且可以访问。")
            elif event == "progress":
                processed, total, candidates = value
                self.update_progress(processed, total)
                self.status.set(f"对比中 · 已找到 {candidates} 个候选")
            else:
                was_comparing = self.comparing
                self.comparing = self.busy = False
                if event == "loaded":
                    self.query_image, preview, self.query_path = value
                    self.query_preview.set(preview)
                    self.show_ready_status()
                elif event == "results":
                    matches, compared, inaccessible, total, suffix_count = value
                    self.progress.stop()
                    self.update_progress(total, total)
                    self.results = {record.export: evidence for record, evidence in matches}
                    self.fill(record for record, _ in matches)
                    first = next(iter(self.rows), None)
                    if first:
                        self.tree.selection_set(first)
                        self.select()
                    visual_count = len(matches) - min(suffix_count, SUFFIX_RESULT_LIMIT)
                    self.result_summary.set(f"截图匹配 {visual_count} · 后缀查找 {suffix_count}" if suffix_count else
                                            f"已比对 {compared} 份 · {visual_count} 个候选")
                    summary = f"对比完成，找到 {len(matches)} 个候选。请查看右侧对照。" if matches else (
                        "对比完成，没找到相似文件。可尝试换一张更完整的截图。" if compared else
                        "没有符合关键词的文件。可以缩短关键词或清空关键词后再找。" if total and not inaccessible else
                        "所选文件无法比对。请确认文件可读且有可用预览。" if total else
                        "这个文件夹里没有所选格式的文件。可以更改左侧「搜索格式」。"
                    )
                    if suffix_count:
                        summary = f"查找完成，截图匹配 {visual_count} 项，按后缀或关键词找到 {suffix_count} 项。"
                        if suffix_count > SUFFIX_RESULT_LIMIT:
                            summary += f"后缀结果显示前 {SUFFIX_RESULT_LIMIT} 项。"
                    self.status.set(summary + (f" 有 {inaccessible} 项无法读取或无兼容预览。" if inaccessible else ""))
                    self.view.notice.show(visual_count + suffix_count, self.view.palette)
                else:
                    if was_comparing:
                        self.progress.stop()
                        self.progress.set_mode("determinate")
                        self.progress_value.set(0)
                        self.progress_text.set("对比未完成")
                        self.result_summary.set("对比未完成。")
                    self.status.set("对比未完成，请检查文件夹和截图后再试。" if was_comparing else
                                    "无法读取这张截图。请重新截图，或从文件选择图片。")
                self.sync_buttons()
        self.root.after(50, self.poll)

    def close(self):
        self.invalidate_search()
        self.view.notice.dismiss()
        self.root.destroy()


def main():
    enable_windows_dpi()
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        import time

        from smoke import run, run_file_formats

        run(DEMO_DIR)
        run_file_formats(DEMO_DIR)
        root = TkinterDnD.Tk()
        root.withdraw()
        try:
            app = App(root)
            def wait_for_idle():
                deadline = time.monotonic() + 30
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.02)
                assert not app.busy, "The desktop operation timed out."

            assert app.buttons["paste"].instate(("!disabled",))
            app.load_query(read_image(DEMO_DIR / "客户截图.jpg"))
            wait_for_idle()
            assert app.catalog is None and app.query_image is not None
            assert app.query_preview.image is not None
            choose_project = app.choose_project
            app.choose_project = lambda: False
            app.buttons["compare"].invoke()
            assert app.catalog is None and "还未选择搜索文件夹" in app.status.get()
            app.choose_project = lambda: app.open_project(DEMO_DIR, demo=True)
            app.buttons["compare"].invoke()
            assert app.comparing and app.progress.mode == "indeterminate"
            wait_for_idle()
            assert app.location_path.get().endswith("导出图 B.png")
            assert app.progress_value.get() == 100 and "3/3" in app.progress_text.get()
            app.choose_project = choose_project
            app.open_demo()
            wait_for_idle()
            assert not app.rows and "开始对比" in app.status.get()
            assert app.search_suffixes == DEFAULT_SUFFIXES and app.active_suffixes == {".png"}
            app.set_search_formats([])
            app.buttons["compare"].invoke()
            assert not app.busy and "至少一种文件格式" in app.status.get()
            app.set_search_formats({".pdf"})
            app.buttons["compare"].invoke()
            wait_for_idle()
            assert not app.rows and "没有所选格式" in app.status.get()
            app.set_search_formats({".png"})
            app.buttons["compare"].invoke()
            wait_for_idle()
            assert len(app.rows) == 1 and app.location_path.get().endswith("可编辑原稿 B.svg")
            assert app.progress_value.get() == 100
            assert app.buttons["reveal"].instate(("!disabled",))
            app.load_query(Image.new("RGB", (200, 200), "black"))
            assert app.buttons["paste"].instate(("!disabled",))
            app.load_query(read_image(DEMO_DIR / "客户截图.jpg"))
            wait_for_idle()
            assert not app.rows and "开始对比" in app.status.get()
            app.buttons["compare"].invoke()
            wait_for_idle()
            assert len(app.rows) == 1 and app.location_path.get().endswith("可编辑原稿 B.svg")
            app.clear_query()
            assert app.query_preview.image is None and not app.location_path.get()
        finally:
            root.destroy()
        return
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
