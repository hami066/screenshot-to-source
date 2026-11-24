import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from catalog import CATALOG_NAME, IMAGE_SUFFIXES, Catalog, scan_exports
from design_preview import DESIGN_SUFFIXES
from desktop_theme import header_mask
from local_paths import local_path, project_file
from matcher import Matcher, read_image
from smoke import run, run_file_formats

DEMO = Path(__file__).resolve().parent.parent / "demo"


class DesktopThemeTests(unittest.TestCase):
    def test_search_watermark_keeps_blurred_glyphs_inside_layer(self):
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                width, height = round(208 * scale), round(66 * scale)
                bounds = header_mask((width, height), "search").getbbox()
                self.assertIsNotNone(bounds)
                left, top, right, bottom = bounds
                self.assertGreater(min(left, top, width - right, height - bottom), 0)


class DesktopCoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.export = self.root / "导出图 B.png"
        self.source = self.root / "可编辑原稿 B.svg"
        shutil.copyfile(DEMO / self.export.name, self.export)
        shutil.copyfile(DEMO / self.source.name, self.source)

    def test_cropped_compressed_and_marked_screenshot(self):
        run(DEMO)

    def test_design_composites_and_second_pdf_page(self):
        run_file_formats(DEMO)

    def test_design_scan_defaults_and_optional_exports(self):
        for suffix in (".psd", ".psb", ".ai", ".pdf"):
            (self.root / ("设计稿" + suffix)).touch()
        args = (self.root, set(), lambda: False, lambda _: None)
        found, skipped = scan_exports(*args, suffixes=DESIGN_SUFFIXES)
        self.assertEqual({Path(name).suffix for name in found}, DESIGN_SUFFIXES)
        self.assertEqual(skipped, 0)
        combined, _ = scan_exports(*args, suffixes=DESIGN_SUFFIXES | IMAGE_SUFFIXES, prioritize=DESIGN_SUFFIXES)
        self.assertEqual(combined[:-1], found)
        self.assertEqual(combined[-1], self.export.name)

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
