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

THE FROZEN SNAPSHOT IS THE AUTHORITY
------------------------------------
Every expected value -- checksum, size, version identity, path, filename -- is
read from `snapshot.manifest`, **never** from the live `DocumentVersion` row.

That distinction is the whole guarantee, and it is reachable rather than
theoretical. `DocumentVersion.sha256_checksum`, `size_bytes` and `storage_key`
carry no database immutability trigger; this app's own tests already rewrite
`storage_key` with a plain `objects.update()`. If a bug, a migration or a raw
cursor rewrote all three together after a freeze, an exporter that compared
streamed bytes against *today's* metadata would happily agree with itself and
ship an archive whose files contradict the `manifest.json` sitting beside them.

So the comparison is: stream `entry.document_version.storage_key`, hash it, and
check the result against what the **frozen manifest** said those bytes were.
Live metadata is used for exactly one thing -- finding the object -- and is
never trusted to describe it.

The entry set is checked the same way: every active entry must appear in the
manifest exactly once, the manifest must contain nothing extra, and each row's
version identity, logical path and filename must match the live entry. The
`0002` triggers should already make drift impossible; the exporter fails closed
anyway, because "should be impossible" is not a property an archive can rely on.

**This is not a claim that `DocumentVersion` is immutable.** The database does
not prove that today, and nothing here pretends otherwise -- the snapshot is
treated as the authority precisely because the live row cannot be.
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


def _manifest_rows_by_entry(snapshot) -> dict:
    """The frozen rows, keyed by entry public id.

    A duplicate key would mean the manifest describes one entry twice, which no
    freeze can produce -- so it is a corrupted snapshot, and the export refuses
    rather than picking whichever row it saw last.
    """
    rows: dict = {}
    for row in snapshot.manifest.get("entries", []):
        key = row.get("entry_public_id")
        if key in rows:
            raise ExportError("The frozen manifest names an entry more than once.")
        rows[key] = row
    return rows


def _expected_for(entry, rows: dict) -> dict:
    """The frozen row for one live entry, with every identity re-proved.

    Drift between the live entry and the snapshot is never accepted quietly. If
    they disagree, one of them is wrong and the archive cannot say which, so it
    is not produced.
    """
    row = rows.get(str(entry.public_id))
    if row is None:
        raise ExportError("A package entry is not named in the frozen manifest.")

    if row.get("document_version_public_id") != str(entry.document_version.public_id):
        raise ExportError("An entry cites a different version than the frozen manifest.")
    if row.get("logical_path") != entry.logical_path:
        raise ExportError("An entry has a different path than the frozen manifest.")
    if row.get("export_filename") != entry.export_filename:
        raise ExportError("An entry has a different filename than the frozen manifest.")
    if not row.get("document_checksum_sha256"):
        raise ExportError("The frozen manifest has no checksum for an entry.")
    return row


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

    entries = list(entries)
    rows = _manifest_rows_by_entry(snapshot)

    # The live set and the frozen set must be the same set. Extra live entries
    # and missing ones are both refusals: an archive that quietly contains more
    # or less than its manifest describes is worse than no archive.
    if len(entries) != len(rows) or len(entries) != int(snapshot.entry_count):
        raise ExportError("The package no longer matches its frozen manifest.")
    live_keys = {str(e.public_id) for e in entries}
    if live_keys != set(rows):
        raise ExportError("The package no longer matches its frozen manifest.")

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
            expected = _expected_for(entry, rows)
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

            # Compared against the FROZEN manifest, never against the live
            # DocumentVersion row. Live metadata found the object; only the
            # snapshot gets to say what the object should be. See the module
            # docstring for why the difference is reachable.
            if digest.hexdigest() != expected["document_checksum_sha256"]:
                raise ExportError("A cited file no longer matches the frozen manifest checksum.")
            if size != int(expected["file_size_bytes"]):
                raise ExportError("A cited file no longer matches the frozen manifest size.")

            written += 1
            total += size

    return {"entry_count": written, "total_bytes": total}
