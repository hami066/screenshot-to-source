"""Match a crop or annotated screenshot to a rendered export, entirely in memory."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256

import cv2
import numpy as np
from PIL import Image, ImageOps

from catalog import IMAGE_BYTE_LIMIT
from design_preview import (
    MAX_PIXELS, PDF_SUFFIXES, PHOTOSHOP_SUFFIXES, PreviewUnavailable, pdf_document,
    photoshop_preview, render_pdf_page,
)
from local_paths import local_path

IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "BMP")

cv2.setNumThreads(2)


def read_image(path):
    path = local_path(path)
    if path.stat().st_size > IMAGE_BYTE_LIMIT:
        raise ValueError("The image exceeds the 96 MB limit.")
    with path.open("rb") as stream, Image.open(stream, formats=IMAGE_FORMATS) as image:
        return normalize_image(image)


def normalize_image(image):
    if not 0 < image.width * image.height <= MAX_PIXELS:
        raise ValueError("The image must contain between 1 and 48 million pixels.")
    image = ImageOps.exif_transpose(image)
    if "A" in image.getbands() or "transparency" in image.info:
        foreground = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(foreground)
        image = background
    return image.convert("RGB")


def read_reference(path, page=None):
    path = local_path(path)
    suffix = path.suffix.lower()
    if suffix in PHOTOSHOP_SUFFIXES:
        return photoshop_preview(path)
    if suffix in PDF_SUFFIXES:
        with pdf_document(path) as document:
            if page is None or not 0 <= page < len(document):
                raise PreviewUnavailable("No PDF page is available.")
            return render_pdf_page(document, page)
    return read_image(path)


@dataclass(frozen=True)
class Evidence:
    exact: bool
    inliers: int
    ratio: float
    box: tuple[int, int, int, int]
    image_size: tuple[int, int]
    page: int | None = None


@dataclass
class Features:
    size: tuple[int, int]
    points: np.ndarray
    descriptors: np.ndarray | None
    offset: tuple[int, int]
    scale: tuple[float, float]


class Matcher:
    def __init__(self):
        self.detector = cv2.SIFT_create(nfeatures=1500)
        self.comparator = cv2.BFMatcher(cv2.NORM_L2)
        self.cache = OrderedDict()
        self.cache_bytes = 0

    def _features(self, image, offset=(0, 0), max_side=1600):
        factor = min(1, max_side / max(image.size))
        width, height = (max(1, round(n * factor)) for n in image.size)
        reduced = image.resize((width, height), Image.Resampling.LANCZOS) if factor < 1 else image
        gray = np.asarray(reduced.convert("L"))
        points, descriptors = self.detector.detectAndCompute(gray, None)
        return Features(
            (width, height),
            np.asarray([point.pt for point in points], dtype=np.float32),
            descriptors,
            offset,
            (image.width / width, image.height / height),
        )

    @staticmethod
    def _digest(image):
        return image.size, sha256(image.tobytes()).digest()

    def query(self, image):
        return self._digest(image), self._features(image)

    def _reference(self, path, page, open_image):
        meta = path.stat()
        key = (path, page, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key][0]
        image = open_image()
        width, height = image.size
        variants = [self._features(image)]
        short, long = sorted(image.size)
        if long > 2.2 * short:
            vertical = height > width
            length = min(long, max(900, round(short * 1.7)))
            if length < long:
                stride = length * 2 // 3
                starts = range(0, long - length, stride)
                for start in (*starts, long - length):
                    box = (0, start, width, start + length) if vertical else (start, 0, start + length, height)
                    variants.append(self._features(image.crop(box), box[:2]))
        prepared = self._digest(image), variants
        weight = sum(
            view.points.nbytes + (view.descriptors.nbytes if view.descriptors is not None else 0)
            for view in variants
        )
        budget = 96 * 1024 * 1024
        if weight <= budget:
            while self.cache and self.cache_bytes + weight > budget:
                _, (_, removed) = self.cache.popitem(last=False)
                self.cache_bytes -= removed
            self.cache[key] = prepared, weight
            self.cache_bytes += weight
        return prepared

    def match(self, query, path, cancelled=lambda: False):
        path = local_path(path)
        if path.suffix.lower() not in PDF_SUFFIXES:
            return self._match_reference(query, path, None, partial(read_reference, path))
        with pdf_document(path) as document:
            best = None
            rendered = 0
            for page in range(len(document)):
                if cancelled():
                    return None
                try:
                    match = self._match_reference(query, path, page, partial(render_pdf_page, document, page))
                except (OSError, ValueError, Image.DecompressionBombError):
                    continue
                rendered += 1
                if match:
                    if best is None or (match.exact, match.inliers, match.ratio) > (best.exact, best.inliers, best.ratio):
                        best = replace(match, page=page)
                    if match.exact:
                        break
            if not rendered:
                raise PreviewUnavailable("No PDF page could be rendered.")
            return best

    def _match_reference(self, query, path, page, open_image):
        query_digest, screenshot = query
        reference_digest, variants = self._reference(path, page, open_image)
        size = reference_digest[0]
        if query_digest == reference_digest:
            return Evidence(True, 0, 1, (0, 0, *size), size)
        best = None
        for reference in variants:
            evidence = self._compare(screenshot, reference, size)
            if evidence and (best is None or (evidence.inliers, evidence.ratio) > (best.inliers, best.ratio)):
                best = evidence
        return best

    def _compare(self, screenshot, reference, size):
        if (
            screenshot.descriptors is None
            or reference.descriptors is None
            or len(screenshot.descriptors) < 10
            or len(reference.descriptors) < 10
        ):
            return None
        pairs = self.comparator.knnMatch(screenshot.descriptors, reference.descriptors, k=2)
        accepted = {}
        for first, second in pairs:
            if first.distance < 0.76 * second.distance:
                previous = accepted.get(first.trainIdx)
                if previous is None or first.distance < previous.distance:
                    accepted[first.trainIdx] = first
        if len(accepted) < 10:
            return None
        matches = list(accepted.values())
        screen_points = screenshot.points[[m.queryIdx for m in matches]]
        image_points = reference.points[[m.trainIdx for m in matches]]
        matrix, mask = cv2.findHomography(screen_points, image_points, cv2.RANSAC, 3.5)
        if matrix is None or mask is None:
            return None
        valid = mask.ravel().astype(bool)
        count = int(valid.sum())
        ratio = count / len(matches)
        if count < 10 or ratio < 0.48:
            return None
        screen_hull = cv2.convexHull(screen_points[valid])
        image_hull = cv2.convexHull(image_points[valid])
        if cv2.contourArea(screen_hull) < max(100, np.prod(screenshot.size) * 0.0015):
            return None
        if cv2.contourArea(image_hull) < 100:
            return None
        points = image_points[valid] * reference.scale + reference.offset
        left, top = np.floor(points.min(axis=0)).astype(int)
        right, bottom = np.ceil(points.max(axis=0)).astype(int)
        if min(right - left, bottom - top) < 18:
            return None
        padding = max(4, round(min(right - left, bottom - top) * 0.045))
        box = max(0, left - padding), max(0, top - padding), min(size[0], right + padding), min(size[1], bottom + padding)
        return Evidence(False, count, ratio, box, size)
