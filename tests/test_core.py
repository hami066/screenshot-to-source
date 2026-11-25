import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageColor, ImageDraw

from app import DEFAULT_SUFFIXES, App
from catalog import CATALOG_NAME, IMAGE_SUFFIXES, Catalog, parse_suffixes, scan_exports
from design_preview import ARCHIVE_ENTRIES, DESIGN_SUFFIXES, PreviewUnavailable
from desktop_theme import DARK, LIGHT, paint_backdrop
from local_paths import local_path, project_file
from matcher import Matcher, read_image, read_reference
from smoke import run, run_file_formats

DEMO = Path(__file__).resolve().parent.parent / "demo"


class DesktopThemeTests(unittest.TestCase):
    def test_header_tint_stays_between_navigation_and_workspace(self):
        for palette in (LIGHT, DARK):
            with self.subTest(dark=palette.dark):
                background = paint_backdrop(palette, (945, 610), int)
                self.assertEqual(background.getpixel((470, 10)), ImageColor.getrgb(palette.caption))
                self.assertNotEqual(background.getpixel((470, 60)), ImageColor.getrgb(palette.base))
                self.assertEqual(background.getpixel((470, 240)), ImageColor.getrgb(palette.base))


class DesktopCoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.export = self.root / "导出图 B.png"
        self.source = self.root / "可编辑原稿 B.svg"
        shutil.copyfile(DEMO / self.export.name, self.export)
        shutil.copyfile(DEMO / self.source.name, self.source)

    def test_cropped_compressed_and_marked_screenshot(self):
        run(DEMO)

    def test_design_composites_and_second_pdf_page(self):
        run_file_formats(DEMO)

    def test_design_scan_defaults_and_optional_exports(self):
        nested = self.root / "子文件夹"
        nested.mkdir()
        for suffix in (*DESIGN_SUFFIXES, ".pptx", ".tst"):
            (nested / ("设计稿" + suffix.upper())).touch()
        args = (self.root, set(), lambda: False, lambda _: None)
        found, skipped = scan_exports(*args, suffixes=DEFAULT_SUFFIXES)
        self.assertEqual({Path(name).suffix.lower() for name in found}, DEFAULT_SUFFIXES)
        self.assertEqual(skipped, 0)
        combined, _ = scan_exports(*args, suffixes=DEFAULT_SUFFIXES | IMAGE_SUFFIXES, prioritize=DESIGN_SUFFIXES)
        self.assertEqual(combined[:-1], found)
        self.assertEqual(combined[-1], self.export.name)
        selected, _ = scan_exports(*args, suffixes={".psd", ".pptx"})
        self.assertEqual({Path(name).suffix.lower() for name in selected}, {".psd", ".pptx"})

    def test_archived_document_previews_find_sources_and_skip_missing_previews(self):
        screenshot = read_image(DEMO / "客户截图.jpg")
        artwork = read_image(self.export)
        with BytesIO() as stream:
            artwork.save(stream, format="PNG")
            preview = stream.getvalue()
        for suffix, (document, alternatives) in ARCHIVE_ENTRIES.items():
            path = self.root / f"设计稿{suffix}"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                archive.writestr(document, b"test fixture")
                preview_path = alternatives[-1]
                archive.writestr(preview_path, preview)
        with ZipFile(self.root / "无封面.fig", "w") as archive:
            archive.writestr("canvas.fig", b"test fixture")
        (self.root / "损坏.fig").write_bytes(b"invalid ZIP data")
        events = {}
        App.compare_files(events.__setitem__, Event(), self.root, {}, Matcher(), screenshot, set(), ARCHIVE_ENTRIES.keys())
        matches, compared, skipped, total, suffix_count = events["results"]
        self.assertEqual({Path(record.export).suffix for record, _ in matches}, ARCHIVE_ENTRIES.keys())
        self.assertEqual((compared, skipped, total, suffix_count), (5, 2, 7, 0))
        self.assertEqual(read_reference(self.root / "设计稿.fig").tobytes(), artwork.tobytes())
        with self.assertRaises(PreviewUnavailable):
            read_reference(self.root / "无封面.fig")

    def test_tiff_and_gif_decode_the_first_image(self):
        for extension in ("tif", "gif"):
            path = self.root / f"序列.{extension}"
            first = Image.new("RGB", (64, 64), "blue")
            first.save(path, save_all=True, append_images=[Image.new("RGB", first.size, "red")])
            self.assertEqual(read_image(path).getpixel((10, 10)), (0, 0, 255))

    def test_custom_suffixes_list_files_and_txt_can_search_content(self):
        (self.root / "备忘录.TXT").write_text("项目代号 Horizon", encoding="utf-16")
        (self.root / "会议记录.txt").write_text("请确认测试文稿", encoding="gb18030")
        (self.root / "Horizon 设计.CDR").write_bytes(b"no preview needed")
        (self.root / "另一个设计.CDR").touch()
        suffixes = parse_suffixes("TXT，.cdr .txt")
        self.assertEqual(suffixes, {".txt", ".cdr"})
        with self.assertRaises(ValueError):
            parse_suffixes("C:/folder/example.txt")

        def search(keyword):
            events = {}
            App.compare_files(events.__setitem__, Event(), self.root, {}, None, None, set(), suffixes, keyword)
            matches, compared, skipped, total, suffix_count = events["results"]
            self.assertEqual((compared, skipped, total, suffix_count), (0, 0, 4, len(matches)))
            self.assertTrue(all(evidence is None for _, evidence in matches))
            return {record.export for record, _ in matches}

        self.assertEqual(search("horizon"), {"备忘录.TXT", "Horizon 设计.CDR"})
        self.assertEqual(search("测试"), {"会议记录.txt"})
        self.assertEqual(len(search("")), 4)

    def test_shared_crop_preserves_multiple_candidates(self):
        version = read_image(self.export)
        changed = self.root / "version-2.png"
        ImageDraw.Draw(version).rectangle((0, 790, 780, 960), fill="blue")
        version.save(changed)
        matcher = Matcher()
        query = matcher.query(read_image(DEMO / "客户截图.jpg"))
        self.assertIsNotNone(matcher.match(query, self.export))
        self.assertIsNotNone(matcher.match(query, changed))

    def test_long_image_and_unrelated_screenshot(self):
        full = Image.new("RGB", (780, 5700), "white")
        full.paste(read_image(self.export), (0, 4540))
        long_image = self.root / "long.png"
        full.save(long_image)
        matcher = Matcher()
        query = matcher.query(read_image(DEMO / "客户截图.jpg"))
        match = matcher.match(query, long_image)
        self.assertIsNotNone(match)
        self.assertGreater(match.box[1], 4540)
        blank = matcher.query(Image.new("RGB", (800, 800), "gray"))
        self.assertIsNone(matcher.match(blank, long_image))

    def test_exact_match_survives_filename_change(self):
        matcher = Matcher()
        result = matcher.match(matcher.query(read_image(self.export)), self.export)
        self.assertTrue(result.exact)

    def test_manual_save_and_replaced_export(self):
        catalog = Catalog(self.root)
        record = catalog.add(self.export, self.source, "04")
        self.assertFalse((self.root / CATALOG_NAME).exists())
        self.assertEqual(catalog.paths(record), (self.export, self.source))
        catalog.save()
        reopened = Catalog(self.root)
        self.assertEqual(reopened.records, {self.export.name: record})
        shutil.copyfile(DEMO / "导出图 A.png", self.export)
        self.assertEqual(reopened.paths(record), (self.export, None))

    def test_denied_source_is_not_returned(self):
        catalog = Catalog(self.root)
        record = catalog.add(self.export, self.source)
        real_open = Path.open

        def deny_only_source(path, *args, **kwargs):
            if path == self.source:
                raise PermissionError("source denied")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", deny_only_source):
            self.assertEqual(catalog.paths(record), (self.export, None))

    def test_catalog_path_escapes_are_rejected(self):
        for relative in ("../private.psd", "/private.psd", "C:/private.psd", "folder\\private.psd"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                project_file(self.root, relative)
        with self.assertRaises(ValueError):
            local_path("unscoped.png")

    def test_concurrent_catalog_saves_preserve_other_records(self):
        first = Catalog(self.root)
        other = Catalog(self.root)
        additional = self.root / "extra.png"
        shutil.copyfile(self.export, additional)
        first.add(self.export, self.source)
        other.add(additional)
        first.save()
        other.save()
        self.assertEqual(set(Catalog(self.root).records), {self.export.name, additional.name})

    def test_scan_discovers_unregistered_images_and_excludes_query_file(self):
        nested = self.root / "exports"
        nested.mkdir()
        shutil.copyfile(self.export, nested / "a.JFIF")
        query = self.root / "query.jpg"
        shutil.copyfile(DEMO / "客户截图.jpg", query)
        found, skipped = scan_exports(self.root, {query}, lambda: False, lambda _: None)
        self.assertEqual(set(found), {self.export.name, "exports/a.JFIF"})
        self.assertEqual(skipped, 0)
        self.assertFalse((self.root / CATALOG_NAME).exists())

    def test_remember_saves_immediately_and_rolls_back_on_failure(self):
        catalog = Catalog(self.root)
        catalog.remember(self.export, self.source, "画板 B")
        self.assertEqual(Catalog(self.root).records[self.export.name].artboard, "画板 B")
        with patch.object(catalog, "save", side_effect=PermissionError("read-only directory")):
            with self.assertRaises(PermissionError):
                catalog.remember(self.export, self.source, "画板 C")
        self.assertEqual(catalog.records[self.export.name].artboard, "画板 B")
        self.assertFalse(catalog.changes)
