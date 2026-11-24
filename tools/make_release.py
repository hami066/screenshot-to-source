"""Assemble the portable Windows ZIP from a PyInstaller one-directory build."""

import importlib.metadata
import shutil
import sys
from hashlib import file_digest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent


def copy_notices(portable):
    for name in ("README.md", "SECURITY.md", "LICENSE"):
        shutil.copy2(ROOT / name, portable / name)
    notices = portable / "third-party-licenses"
    packages = [
        "numpy", "opencv-python-headless", "Pillow", "tkinterdnd2", "PyInstaller",
        "pypdfium2", "psd-tools", "attrs",
    ]
    if sys.platform == "darwin":
        packages.extend(("pyobjc-core", "pyobjc-framework-Cocoa"))
    for package_name in packages:
        distribution = importlib.metadata.distribution(package_name)
        for file in distribution.files or ():
            if not (
                file.name.lower().startswith(("license", "copying", "notice"))
                or "licenses" in file.parts
            ):
                continue
            source = distribution.locate_file(file)
            if source.is_file() and source.suffix.lower() != ".py":
                target = notices / package_name / file
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for path in (Path(sys.base_prefix), Path(sys.base_prefix) / "tcl"):
        for file in path.glob("LICENSE*"):
            if file.is_file():
                shutil.copy2(file, notices / f"Python-{file.name}")


def package(portable, output):
    shutil.copytree(ROOT / "demo", portable / "demo", dirs_exist_ok=True)
    (portable / "tools").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "tools" / "New-OfflineDemo.ps1", portable / "tools")
    copy_notices(portable)

    archive = output / "screenshot-to-source-windows-x64.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=6) as target:
        for file in sorted(portable.rglob("*")):
            if file.is_file():
                target.write(file, Path(portable.name) / file.relative_to(portable))
    with archive.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(archive.resolve())


if __name__ == "__main__":
    package(Path(sys.argv[1]), Path(sys.argv[2]))
