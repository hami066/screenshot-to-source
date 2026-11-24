"""Read local document previews without starting the authoring applications."""

import io
import math
import struct
import threading
import zlib
from contextlib import contextmanager
from zipfile import BadZipFile, ZipFile

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageCms, ImageOps
from psd_tools.psd.header import FileHeader
from psd_tools.psd.image_data import ImageData

PHOTOSHOP_SUFFIXES = {".psd", ".psb"}
PDF_SUFFIXES = {".pdf", ".ai"}
OFFICE_ENTRIES = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml", ".xlsx": "xl/workbook.xml"}
ARCHIVE_ENTRIES = {
    ".sketch": ("document.json", ("previews/preview.png",)),
    ".fig": ("canvas.fig", ("thumbnail.png",)),
    **{suffix: (entry, tuple(f"docProps/thumbnail.{ext}" for ext in ("jpeg", "jpg", "png")))
       for suffix, entry in OFFICE_ENTRIES.items()},
}
DESIGN_SUFFIXES = PHOTOSHOP_SUFFIXES | PDF_SUFFIXES | {".sketch", ".fig"}
DOCUMENT_SUFFIXES = DESIGN_SUFFIXES | OFFICE_ENTRIES.keys()
MAX_PIXELS = 48_000_000
PSD_COMPOSITE_BYTES = 160 * 1024 * 1024
PDFIUM_LOCK = threading.RLock()
ZIP_END = struct.Struct("<4s4H2LH")
ZIP_DIRECTORY_LIMIT = 16 * 1024 * 1024
PREVIEW_BYTE_LIMIT = 24 * 1024 * 1024


class PreviewUnavailable(ValueError):
    """The file cannot supply a local preview."""


def check_archive_directory(stream):
    # ZipFile loads the central directory at open. Bound it before handing over the stream.
    size = stream.seek(0, 2)
    stream.seek(max(0, size - 65535 - ZIP_END.size - 20))
    tail = stream.read()
    start = tail.rfind(b"PK\x05\x06")
    if start < 0 or len(tail) - start < ZIP_END.size:
        raise PreviewUnavailable("The document has no compatible ZIP directory.")
    _, disk, directory_disk, entries_on_disk, entries, length, offset, comment = ZIP_END.unpack_from(tail, start)
    zip64 = start >= 20 and tail[start - 20:start - 16] == b"PK\x06\x07"
    if (disk or directory_disk or entries != entries_on_disk or entries > 50_000 or zip64
            or length > ZIP_DIRECTORY_LIMIT or offset + length > size
            or start + ZIP_END.size + comment != len(tail)):
        raise PreviewUnavailable("Unsupported ZIP directory size or layout.")


@contextmanager
def embedded_preview(path):
    document_entry, preview_entries = ARCHIVE_ENTRIES[path.suffix.lower()]
    try:
        with path.open("rb") as stream:
            check_archive_directory(stream)
            with ZipFile(stream) as archive:
                archive.getinfo(document_entry)
                preview = next((archive.NameToInfo[name] for name in preview_entries if name in archive.NameToInfo), None)
                if preview is None or not (0 < preview.file_size <= PREVIEW_BYTE_LIMIT
                                           and 0 < preview.compress_size <= PREVIEW_BYTE_LIMIT):
                    raise PreviewUnavailable("The document has no usable embedded preview.")
                data = archive.read(preview)
        with Image.open(io.BytesIO(data), formats=("PNG", "JPEG")) as image:
            yield image
    except (BadZipFile, KeyError, RuntimeError, NotImplementedError, EOFError, struct.error, zlib.error) as error:
        raise PreviewUnavailable("The document has no readable embedded preview.") from error


def read_integer(stream, size, *, signed=False):
    content = stream.read(size)
    if len(content) != size:
        raise PreviewUnavailable("Truncated Photoshop file.")
    return int.from_bytes(content, "big", signed=signed)


def section_end(stream, size, file_size):
    length = read_integer(stream, size)
    end = stream.tell() + length
    if end > file_size:
        raise PreviewUnavailable("Invalid Photoshop section size.")
    return end


def photoshop_resources(stream, end):
    profile = None
    while stream.tell() + 12 <= end:
        if stream.read(4) != b"8BIM":
            break
        resource = read_integer(stream, 2)
        name_length = read_integer(stream, 1)
        stream.seek(name_length + (name_length + 1) % 2, 1)
        length = read_integer(stream, 4)
        next_resource = stream.tell() + length + length % 2
        if next_resource > end:
            break
        if resource == 1057 and length >= 5 and stream.read(5)[4] == 0:
            raise PreviewUnavailable("The Photoshop file has no saved composite.")
        if resource == 1039 and length <= 4 * 1024 * 1024:
            profile = stream.read(length)
        stream.seek(next_resource)
    stream.seek(end)
    return profile


def photoshop_preview(path):
    size = path.stat().st_size
    try:
        with path.open("rb") as stream:
            header = FileHeader.read(stream)
            color_mode = int(header.color_mode)
            mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(color_mode)
            pixels = header.width * header.height
            depth = header.depth
            if (
                not mode or depth not in (8, 16) or not 0 < pixels <= MAX_PIXELS
                or not len(mode) <= header.channels
                or pixels * header.channels * (depth // 8) > PSD_COMPOSITE_BYTES
            ):
                raise PreviewUnavailable("Unsupported Photoshop composite size or color mode.")
            stream.seek(section_end(stream, 4, size))
            profile = photoshop_resources(stream, section_end(stream, 4, size))
            length_size = 4 if header.version == 1 else 8
            end = section_end(stream, length_size, size)
            alpha = False
            if end - stream.tell() >= length_size + 2:
                alpha = read_integer(stream, length_size) >= 2 and read_integer(stream, 2, signed=True) < 0
            stream.seek(end)
            if not 2 < size - end <= PSD_COMPOSITE_BYTES:
                raise PreviewUnavailable("The saved Photoshop composite is missing or too large.")
            channels = ImageData.read(stream).get_data(header, max_output_bytes=PSD_COMPOSITE_BYTES)
    except (AssertionError, EOFError, OSError, ValueError, struct.error) as error:
        raise PreviewUnavailable(str(error)) from error

    def band(raw):
        if depth == 16:
            raw = (np.frombuffer(raw, dtype=">u2") >> 8).astype(np.uint8).tobytes()
        return Image.frombytes("L", (header.width, header.height), raw)

    planes = [band(data) for data in channels[:len(mode)]]
    if mode == "CMYK":
        planes = [ImageOps.invert(plane) for plane in planes]
    image = Image.merge(mode, planes)
    if profile:
        try:
            image = ImageCms.profileToProfile(
                image, io.BytesIO(profile), ImageCms.createProfile("sRGB"), outputMode="RGB",
            )
        except (OSError, ValueError, ImageCms.PyCMSError):
            pass
    image = image.convert("RGB")
    if alpha and len(channels) > len(mode):
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=band(channels[len(mode)]))
        return background
    return image


@contextmanager
def pdf_document(path):
    with PDFIUM_LOCK, path.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise PreviewUnavailable("PDF content is unavailable.")
        stream.seek(0)
        try:
            document = pdfium.PdfDocument(stream)
            try:
                if path.suffix.lower() == ".ai" and len(document) == 1:
                    page = document[0]
                    try:
                        text_page = page.get_textpage()
                        text = " ".join(text_page.get_text_bounded().casefold().split())
                        if "saved without pdf content" in text:
                            raise PreviewUnavailable("Illustrator PDF compatibility was disabled.")
                    finally:
                        page.close()
                yield document
            finally:
                document.close()
        except pdfium.PdfiumError as error:
            raise PreviewUnavailable(str(error)) from error


def render_pdf_page(document, index):
    page = document[index]
    try:
        width, height = page.get_size()
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise PreviewUnavailable("Invalid PDF page size.")
        short, long = sorted((width, height))
        scale = min(6.0, 27000 / long, math.sqrt(36_000_000 / (width * height)),
                    max(1720 / long, 850 / short))
        bitmap = page.render(scale=scale, draw_annots=True)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    finally:
        page.close()
