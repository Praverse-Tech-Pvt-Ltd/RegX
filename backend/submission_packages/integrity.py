"""Internal package integrity: enumerated reasons, no regulatory conclusions.

**This checks that the package can be exported, and nothing else.** It does not
know what a submission requires, what any agency expects, or whether the
contents are correct. A package can be perfectly valid here and completely wrong
for its purpose; that judgement belongs to people, and this module deliberately
offers no opinion on it.

Every reason is a code, so callers branch on values rather than parse prose and
the frontend maps them to copy. A generated sentence would also carry document
detail that the projection layer withholds from a caller without
`documents.view`.
"""

from django.db import models


class IntegrityIssue(models.TextChoices):
    NO_ACTIVE_ENTRIES = "no_active_entries", "The package has no active entries"
    DOCUMENT_VERSION_UNAVAILABLE = (
        "document_version_unavailable",
        "A cited document version is not available",
    )
    SCAN_NOT_CLEARED = "scan_not_cleared", "A cited document version is not scan-cleared"
    CHECKSUM_MISSING = "checksum_missing", "A cited document version has no checksum"
    DUPLICATE_PATH = "duplicate_path", "Two entries would export to the same path"
    TENANT_MISMATCH = "tenant_mismatch", "An entry does not belong to this tenant"
    CASE_MISMATCH = "case_mismatch", "A dossier section belongs to a different case"
    SECTION_RETIRED = "section_retired", "A linked dossier section has been retired"
    STORAGE_UNAVAILABLE = "storage_unavailable", "A cited file is missing from storage"
    TOO_MANY_ENTRIES = "too_many_entries", "The package exceeds the export entry limit"
    TOO_LARGE = "too_large", "The package exceeds the export size limit"


#: Operational export bounds. Deliberately generous: these exist so no extractor
#: is handed something absurd, not to express a policy about package size. They
#: are settings-overridable because the right number is an operational question
#: for whoever runs the deployment, not a constant this milestone can know.
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB


def max_entries() -> int:
    from django.conf import settings

    return int(getattr(settings, "SUBMISSION_PACKAGE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES))


def max_total_bytes() -> int:
    from django.conf import settings

    return int(getattr(settings, "SUBMISSION_PACKAGE_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES))


def check_package(*, package, entries, verify_storage: bool = False) -> list[dict]:
    """Every problem, not the first one.

    Returning the full list matters: a user fixing a package one refusal at a
    time, re-running, and hitting the next one is a worse experience than seeing
    all four at once -- and freeze uses the same function, so the two can never
    disagree about what "valid" means.

    `verify_storage` costs one existence check per entry, so it is off for the
    interactive validate endpoint and on at freeze, where being wrong is
    permanent.
    """
    from documents.models import ScanStatus

    from .paths import collision_key

    issues: list[dict] = []

    def add(code, entry=None, detail=None):
        issues.append(
            {
                "code": code,
                "entry_public_id": str(entry.public_id) if entry is not None else None,
                "detail": detail,
            }
        )

    entries = list(entries)
    if not entries:
        add(IntegrityIssue.NO_ACTIVE_ENTRIES)
        return issues

    if len(entries) > max_entries():
        add(IntegrityIssue.TOO_MANY_ENTRIES)

    seen_keys: dict[str, str] = {}
    total = 0
    backend = None
    if verify_storage:
        from documents.storage import get_storage_backend

        backend = get_storage_backend()

    for entry in entries:
        if entry.tenant_id != package.tenant_id:
            add(IntegrityIssue.TENANT_MISMATCH, entry)

        version = entry.document_version
        if version is None:
            add(IntegrityIssue.DOCUMENT_VERSION_UNAVAILABLE, entry)
            continue

        if version.document.tenant_id != package.tenant_id:
            add(IntegrityIssue.TENANT_MISMATCH, entry)

        # The document platform's own status, read not reinterpreted. CLEAN is
        # required, matching what `workflows` requires to cite a version as
        # governed evidence: INFECTED, SCAN_FAILED and SCANNER_UNAVAILABLE are
        # non-conclusions rather than clearances, and PENDING has not finished.
        if version.scan_status != ScanStatus.CLEAN:
            add(IntegrityIssue.SCAN_NOT_CLEARED, entry)

        if not version.sha256_checksum:
            add(IntegrityIssue.CHECKSUM_MISSING, entry)

        total += int(version.size_bytes or 0)

        key = collision_key(entry.logical_path, entry.export_filename)
        if key in seen_keys:
            add(IntegrityIssue.DUPLICATE_PATH, entry)
        else:
            seen_keys[key] = str(entry.public_id)

        section = entry.dossier_section
        if section is not None:
            if section.tenant_id != package.tenant_id:
                add(IntegrityIssue.TENANT_MISMATCH, entry)
            elif section.dossier.regulatory_case_id != package.regulatory_case_id:
                add(IntegrityIssue.CASE_MISMATCH, entry)
            if section.retired_at is not None:
                # Reported, not fatal on its own: a section retired after the
                # entry was added is a traceability note that has gone stale,
                # not a reason the bytes cannot be exported. Freeze treats it as
                # blocking only because a frozen manifest should not record a
                # link that no longer means anything.
                add(IntegrityIssue.SECTION_RETIRED, entry)

        if backend is not None and version.storage_key:
            try:
                if not backend.exists(version.storage_key):
                    add(IntegrityIssue.STORAGE_UNAVAILABLE, entry)
            except Exception:
                # Fail closed. A storage backend that cannot answer is not the
                # same as one that answered yes.
                add(IntegrityIssue.STORAGE_UNAVAILABLE, entry)

    if total > max_total_bytes():
        add(IntegrityIssue.TOO_LARGE)

    return issues
