"""Check the sample and the locally rendered file formats in a distributed copy."""

import tempfile
from pathlib import Path

from psd_tools import PSDImage

from catalog import Catalog
from design_preview import PreviewUnavailable
from matcher import Matcher, read_image, read_reference


def run(root):
    catalog = Catalog(root, read_saved=False)
    for version in ("A", "B", "C"):
        catalog.add(root / f"导出图 {version}.png", root / f"可编辑原稿 {version}.svg", f"画板 {version}")
    matcher = Matcher()
    query = matcher.query(read_image(root / "客户截图.jpg"))
    matches = []
    for record in catalog.records.values():
        export, source = catalog.paths(record)
        evidence = matcher.match(query, export)
        if evidence:
            matches.append((source.name, evidence))
    assert len(matches) == 1 and matches[0][0] == "可编辑原稿 B.svg", matches
    assert not matches[0][1].exact and matches[0][1].inliers >= 20, matches


def run_file_formats(demo):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        first = read_image(demo / "导出图 A.png")
        second = read_image(demo / "导出图 B.png")
        query_image = read_image(demo / "客户截图.jpg")
        psd = root / "合成预览.psd"
        PSDImage.frompil(second).save(psd)
        assert read_reference(psd).tobytes() == second.tobytes()

        pdf = root / "多页.pdf"
        first.save(pdf, format="PDF", save_all=True, append_images=[second])
        ai = root / "PDF 兼容内容.ai"
        ai.write_bytes(pdf.read_bytes())

        matcher = Matcher()
        query = matcher.query(query_image)
        assert matcher.match(query, psd) is not None
        for path in (pdf, ai):
            evidence = matcher.match(query, path)
            assert evidence is not None and evidence.page == 1, (path, evidence)
            assert read_reference(path, evidence.page).size == evidence.image_size

        unavailable = root / "无兼容预览.ai"
        unavailable.write_bytes(b"%!PS-Adobe-3.0\n")
        try:
            matcher.match(query, unavailable)
        except PreviewUnavailable:
            pass
        else:
            raise AssertionError("An AI without PDF content was accepted.")
