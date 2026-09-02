"""The canonical manifest, and the checksum over it.

WHAT A MANIFEST IS FOR
----------------------
It answers one question permanently: *which exact bytes were in this package
when it was frozen*. Every field below serves that. Nothing else is included --
not because more would be unsafe, but because anything that can drift makes the
checksum a worse answer to the only question being asked.

**It is not an agency format.** No eCTD, no XML backbone, no regional envelope,
no sequence. It is a JSON document RegX writes for RegX.

DETERMINISM IS THE WHOLE POINT
------------------------------
Two freezes of the same package composition must produce byte-identical JSON and
therefore the same SHA-256. So:

  * `json.dumps` with `sort_keys=True` and `separators=(",", ":")` -- no
    whitespace to vary, no key order to vary.
  * `ensure_ascii=False` and a UTF-8 encode, so a non-ASCII path hashes as the
    characters it is rather than as an escape sequence whose spelling could
    change between library versions.
  * entries sorted by `(sequence, entry public_id)` -- `sequence` is what the
    user arranged, and the public id breaks ties that would otherwise depend on
    database row order.
  * **no timestamps inside the hashed structure.** `frozen_at` lives on the
    snapshot row beside the checksum, not inside the bytes it covers: including
    it would mean the same package could never hash the same way twice, which
    defeats every test that proves it does.
  * no database primary keys anywhere -- public ids only, as everywhere else in
    this repository.

`repr()` is never used. Its output is a Python implementation detail and is not
a serialisation format.
"""

import hashlib
import json

#: Bumped if the field set below ever changes, so an old checksum compares
#: unequal instead of silently colliding with a differently-computed value.
MANIFEST_SCHEMA_VERSION = 1


def build_manifest(*, package, entries) -> dict:
    """The canonical structure for one package and its active entries.

    `entries` must already be the active set; this does not filter, because a
    caller that has locked and validated a set of rows should hand exactly those
    rows to the hash rather than have them re-derived from a queryset that could
    resolve differently.

    Every entry field is read from the row or from the exact `DocumentVersion`
    it binds. Nothing is read from `document.current_version`.
    """
    rows = []
    for entry in sorted(entries, key=lambda e: (e.sequence, str(e.public_id))):
        version = entry.document_version
        rows.append(
            {
                "entry_public_id": str(entry.public_id),
                "sequence": int(entry.sequence),
                "logical_path": entry.logical_path,
                "export_filename": entry.export_filename,
                "document_public_id": str(version.document.public_id),
                "document_version_public_id": str(version.public_id),
                "document_version_number": int(version.version_number),
                "document_checksum_sha256": version.sha256_checksum,
                "file_size_bytes": int(version.size_bytes),
                "mime_type": version.detected_mime_type or version.declared_mime_type,
                "dossier_section_public_id": (
                    str(entry.dossier_section.public_id) if entry.dossier_section_id else None
                ),
            }
        )

    return {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "semantics": "internal_package_manifest",
        "package_public_id": str(package.public_id),
        "package_name": package.name,
        "revision_number": int(package.revision_number),
        "case_public_id": str(package.regulatory_case.public_id),
        "entry_count": len(rows),
        "entries": rows,
    }


def canonical_bytes(manifest: dict) -> bytes:
    """The exact bytes the checksum is taken over."""
    return json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def manifest_checksum(manifest: dict) -> str:
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()


def total_bytes(manifest: dict) -> int:
    return sum(row["file_size_bytes"] for row in manifest["entries"])
