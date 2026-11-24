"""Project records. No screenshot, thumbnail or image descriptors are stored."""

import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path

from local_paths import local_path, project_file

CATALOG_NAME = "screenshot-source.sqlite3"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp"}
IMAGE_BYTE_LIMIT = 96 * 1024 * 1024


def fingerprint(path):
    if path.stat().st_size > IMAGE_BYTE_LIMIT:
        raise ValueError("The image exceeds the 96 MB limit.")
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Record:
    export: str
    source: str | None = None
    artboard: str = ""
    fingerprint: str = ""


def scan_exports(root, excluded, cancelled, progress, *, suffixes=IMAGE_SUFFIXES, prioritize=()):
    """Read local directory entries only. Recheck file scope before decoding."""
    found = []
    skipped = 0
    pending = [root]
    while pending and not cancelled():
        folder = pending.pop()
        try:
            with os.scandir(local_path(folder, directory=True)) as entries:
                for entry in entries:
                    if cancelled():
                        return found, skipped
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError:
                        skipped += 1
                        continue
                    if getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    path = folder / entry.name
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(metadata.st_mode) and path.suffix.lower() in suffixes and path not in excluded:
                        found.append(path.relative_to(root).as_posix())
                        if len(found) % 50 == 0:
                            progress(len(found))
        except (OSError, ValueError):
            skipped += 1
    return sorted(found, key=lambda file: (Path(file).suffix.lower() not in prioritize, file.casefold())), skipped


class Catalog:
    def __init__(self, root, *, read_saved=True):
        self.root = local_path(root, directory=True)
        self.path = self.root / CATALOG_NAME
        self.records = {}
        self.changes = {}
        if read_saved and self._checked_path().is_file():
            self._load()

    def _checked_path(self):
        path = local_path(self.path, missing_leaf=True)
        for suffix in ("-journal", "-wal", "-shm"):
            local_path(path.with_name(path.name + suffix), missing_leaf=True)
        return path

    def _load(self):
        file = local_path(self.path)
        with closing(sqlite3.connect(file.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            rows = db.execute("SELECT export, source, artboard, fingerprint FROM records LIMIT 20001").fetchall()
        if len(rows) > 20000:
            raise ValueError("The catalog contains too many records.")
        self.records = {
            export: Record(export, source, artboard[:200], digest[:64])
            for export, source, artboard, digest in rows
            if all(isinstance(field, str) for field in (export, artboard, digest))
            and (source is None or isinstance(source, str))
        }

    def relative_file(self, path):
        path = local_path(path)
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            raise ValueError("Choose a file inside the current project folder.") from None

    def add(self, export, source=None, artboard=""):
        export = self.relative_file(export)
        if Path(export).suffix.lower() not in IMAGE_SUFFIXES | {".pdf"}:
            raise ValueError("Choose an exported image or PDF.")
        if source:
            source = self.relative_file(source)
            if source == export:
                raise ValueError("The reference image and the source must be different files.")
            with project_file(self.root, source).open("rb"):
                pass
        elif export in self.records:
            return self.records[export]
        digest = fingerprint(project_file(self.root, export)) if source else ""
        record = Record(export, source, str(artboard).strip()[:200] if source else "", digest)
        self.changes[export] = self.records[export] = record
        return record

    def paths(self, record):
        export = project_file(self.root, record.export)
        source = None
        if record.source and record.fingerprint and fingerprint(export) == record.fingerprint:
            try:
                candidate = project_file(self.root, record.source)
                with candidate.open("rb"):
                    pass
                source = candidate
            except (OSError, ValueError):
                pass
        return export, source

    def save(self):
        if not self.changes:
            return
        path = self._checked_path()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(export TEXT PRIMARY KEY, source TEXT, artboard TEXT NOT NULL, fingerprint TEXT NOT NULL)"
            )
            db.executemany(
                "INSERT INTO records VALUES (?, ?, ?, ?) "
                "ON CONFLICT(export) DO UPDATE SET source=excluded.source, artboard=excluded.artboard,"
                " fingerprint=excluded.fingerprint",
                [
                    (entry.export, entry.source, entry.artboard, entry.fingerprint)
                    for entry in self.changes.values()
                ],
            )
        self.changes.clear()

    def remember(self, export, source, artboard=""):
        old = self.records.copy()
        previous_changes = self.changes.copy()
        record = self.add(export, source, artboard)
        try:
            self.save()
        except (OSError, ValueError, sqlite3.Error):
            self.records, self.changes = old, previous_changes
            raise
        return record
