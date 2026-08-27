"""Building the export ZIP from a frozen package.

**EXACT VERSIONS.** Every byte written comes from `entry.document_version`. This
module never touches `document.current_version`, and a mutation that makes it do
so turns tests red. That is the single most important property in the milestone:
a package exported today and the same package exported next year must contain
identical files, however many times the underlying documents have been revised.

**The ZIP is an internal container.** It is not an eCTD sequence, not a regional
envelope, not a NeeS structure and not anything an agency ingests. It holds a
`manifest.json` and the files, under the tenant's own paths, and nothing inserts
a folder name that means something to a regulator.

ALL OR NOTHING
--------------
If any entry cannot be retrieved, the whole export fails. A ZIP silently missing
one of ten files is worse than no ZIP at all: it looks complete, and the person
who receives it has no way to tell. This is also why export authorisation is not
per-entry -- see `views`.

TRUST BOUNDARY ON BYTES
-----------------------
Every file is hashed as it is streamed and compared against the checksum the
frozen manifest recorded. That is a real verification, not a metadata check, and
it costs one pass over content that is being read anyway. If the stored bytes
have changed since the version was created, the export fails rather than
producing an archive whose manifest is a lie about its own contents.
"""

import hashlib
import zipfile

#: Read size for streaming a stored object into the archive. Large enough to be
#: efficient, small enough that a 2 GiB file is never a 2 GiB allocation.
CHUNK_SIZE = 1024 * 1024

MANIFEST_NAME = "manifest.json"
FILES_ROOT = "files"


class ExportError(Exception):
    """Raised when an export cannot be produced completely and correctly."""


def archive_name(entry) -> str:
    """The path this entry takes inside the ZIP.

    Always under `files/`, so a `manifest.json` at the archive root can never be
    shadowed by an entry that happens to be called that, and the archive has one
    predictable shape.
    """
    if entry.logical_path:
        return f"{FILES_ROOT}/{entry.logical_path}/{entry.export_filename}"
    return f"{FILES_ROOT}/{entry.export_filename}"


def _assert_safe(name: str) -> None:
    """Last line of defence before a name is written into the archive.

    `paths.normalize_logical_path` already refused all of this at entry time,
    and this checks again at write time anyway: the value has been through a
    database round-trip and a manifest since then, and the cost of being wrong
    here is an archive that escapes its extraction directory on someone else's
    machine.
    """
    if name.startswith("/") or name.startswith("\\"):
        raise ExportError("Refusing to write an absolute path into the archive.")
    if ".." in name.split("/"):
        raise ExportError("Refusing to write a traversing path into the archive.")
    if "\x00" in name:
        raise ExportError("Refusing to write a NUL byte into an archive path.")
    if len(name) >= 2 and name[1] == ":":
        raise ExportError("Refusing to write a drive-qualified path into the archive.")


def write_package_zip(*, snapshot, entries, destination) -> dict:
    """Write the archive to `destination` (a binary file object).

    `entries` are the frozen package's active entries, already resolved. The
    manifest written is the **stored** snapshot manifest, not one recomputed
    now: recomputing would make the archive a function of today's database, and
    the whole point of a snapshot is that it is not.

    Returns counts for the audit row.
    """
    import json

    from documents.storage import get_storage_backend

    backend = get_storage_backend()
    written = 0
    total = 0
    seen: set[str] = set()

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest_bytes = json.dumps(
            snapshot.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        archive.writestr(MANIFEST_NAME, manifest_bytes)

        for entry in entries:
            name = archive_name(entry)
            _assert_safe(name)
            # Case-insensitive, because the extractor's filesystem probably is.
            # Two entries differing only in case would silently overwrite.
            folded = name.casefold()
            if folded in seen:
                raise ExportError("Two entries would write to the same archive path.")
            seen.add(folded)

            version = entry.document_version  # EXACT. Never document.current_version.
            if not version.storage_key:
                raise ExportError("A cited document version has no stored file.")

            digest = hashlib.sha256()
            size = 0
            try:
                stream = backend.retrieve(version.storage_key)
            except Exception as exc:
                raise ExportError("A cited file could not be read from storage.") from exc

            try:
                with archive.open(name, "w") as target:
                    while True:
                        chunk = stream.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
            finally:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()

            # The manifest claims these bytes. If storage disagrees, the archive
            # would ship a manifest that describes something it does not
            # contain, so the export fails instead.
            if digest.hexdigest() != version.sha256_checksum:
                raise ExportError("A cited file no longer matches its recorded checksum.")
            if size != int(version.size_bytes):
                raise ExportError("A cited file no longer matches its recorded size.")

            written += 1
            total += size

    return {"entry_count": written, "total_bytes": total}
