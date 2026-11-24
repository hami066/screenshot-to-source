"""Path checks shared by the catalog and image reader."""

import os
import stat
from pathlib import Path, PureWindowsPath


def local_path(value, *, directory=False, missing_leaf=False):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Choose an absolute local path.")
    if os.name == "nt":
        import ctypes

        if len(path.drive) != 2 or path.anchor != path.drive + "\\":
            raise ValueError("Choose a folder on a local fixed drive.")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        if drive_type(path.anchor) != 3:
            raise ValueError("Choose a folder on a local fixed drive.")
        for name in path.parts[1:]:
            if ":" in name or name.endswith((".", " ")) or PureWindowsPath(name).is_reserved():
                raise ValueError("Unsupported Windows path.")

    item = Path(path.anchor)
    for name in path.parts[1:]:
        item /= name
        try:
            metadata = item.lstat()
        except FileNotFoundError:
            if missing_leaf and item == path:
                return path
            raise
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("Symbolic links, junctions and reparse points are unavailable.")
    metadata = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(metadata.st_mode):
        raise ValueError("Choose a regular local file or project folder.")
    return path


def project_file(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Invalid record path.")
    parts = relative.split("/")
    if any(p in ("", ".", "..") or ":" in p or "\\" in p for p in parts):
        raise ValueError("Records must refer to files inside the project folder.")
    return local_path(root.joinpath(*parts))
