"""Logical export paths: normalisation, and everything that must be refused.

A package entry carries a `logical_path` that becomes a directory inside an
exported ZIP. That makes it the one place in this milestone where tenant-typed
text reaches a filesystem, so it is normalised once, here, and every rule is
enumerated rather than left to whatever `os.path` happens to do on the host.

**The paths are tenant-defined and carry no regulatory meaning.** No CTD, eCTD,
CEP, DMF or ANDA folder structure ships and none is implied: `01-cover/` is an
example, not a standard, and nothing in this module knows what any path means.

WHY NOT REUSE `documents.validators.validate_filename`
------------------------------------------------------
It is the right model and the wrong tool. It validates a single *uploaded
filename* against an extension allow-list (pdf/docx/xlsx/pptx) and rejects every
path separator outright -- correct there, useless for a path that is made of
separators. Its traversal rules are reproduced below; its extension policy
deliberately is not, because an export path is a directory, not a file.

WHAT IS REFUSED, AND WHY EACH ONE MATTERS
-----------------------------------------
`..` anywhere            -- zip slip. An archive entry `../../etc/x` escapes the
                            extraction root on any extractor that joins blindly.
absolute paths           -- `/x` and `C:\\x` extract to a fixed location rather
                            than under the target directory.
backslashes              -- a Windows extractor treats `a\\b` as a directory
                            separator even when the archive says it is one name,
                            so a path that looks flat is not.
UNC prefixes (`\\\\srv`)   -- a network location, not a relative path.
NUL and control bytes    -- truncate the path in any C-level API downstream.
`.` and empty segments   -- `a/./b` and `a//b` are the same directory as `a/b`
                            spelled differently, which defeats duplicate
                            detection unless collapsed first.
trailing dots and spaces -- Windows silently strips them, so `a ` and `a` are
                            the same directory there and different here.
reserved device names    -- `CON`, `NUL`, `COM1`... are devices on Windows
                            whatever extension follows.
depth and length caps    -- an unbounded path is a denial-of-service on the
                            extractor, not a feature.

COLLISION IS A SEPARATE QUESTION FROM VALIDITY
----------------------------------------------
Two *valid* paths can still collide once extracted: `Docs/` and `docs/` differ
here and are the same directory on macOS and Windows, and `café` composed vs
decomposed differ byte-wise while displaying identically. So normalisation
returns both the stored path and a **collision key**, and duplicate detection
compares keys. Storing the case-folded form instead would be lossy -- the tenant
typed `01-Cover` and should get `01-Cover`.
"""

import unicodedata

#: Bounds, generous enough not to interfere with real use and small enough that
#: no extractor is asked to create something absurd.
MAX_PATH_LENGTH = 400
MAX_SEGMENT_LENGTH = 120
MAX_DEPTH = 10

#: Windows device names. Reserved whatever extension follows, so `CON.pdf` is
#: still `CON`. Checked case-insensitively against the segment stem.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class InvalidLogicalPath(ValueError):
    """Raised with an enumerated reason code, never a formatted echo of input.

    The reason is a code because these messages are shown to users and logged,
    and echoing an attacker-supplied path back into either is how a path
    traversal attempt becomes a log-injection or an XSS.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_logical_path(raw: str) -> str:
    """Return the stored form of a logical path, or raise `InvalidLogicalPath`.

    The empty path is legal and means the package root: not every package wants
    folders, and forcing one would be inventing structure.
    """
    if raw is None:
        return ""

    # NFC first. Two spellings of the same string must fail or pass together,
    # and must produce one stored form -- otherwise a duplicate check compares
    # byte sequences that a filesystem considers identical.
    value = unicodedata.normalize("NFC", str(raw)).strip()
    if value == "":
        return ""

    if "\x00" in value:
        raise InvalidLogicalPath("nul_byte", "Path contains a NUL byte.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidLogicalPath("control_character", "Path contains a control character.")
    if "\\" in value:
        # Rejected rather than translated to "/": a caller who typed a backslash
        # meant something this module will not guess at.
        raise InvalidLogicalPath("backslash", "Path must use '/' as its separator.")
    if value.startswith("/"):
        raise InvalidLogicalPath("absolute_path", "Path must be relative.")
    if len(value) >= 2 and value[1] == ":":
        raise InvalidLogicalPath("drive_prefix", "Path must not carry a drive letter.")
    if len(value) > MAX_PATH_LENGTH:
        raise InvalidLogicalPath("too_long", "Path is too long.")

    segments = []
    for segment in value.split("/"):
        if segment == "":
            # `a//b` and a trailing slash both land here. Collapsed rather than
            # refused: the intent is unambiguous and normalising it keeps the
            # duplicate check honest.
            continue
        if segment == ".":
            continue
        if segment == "..":
            raise InvalidLogicalPath("path_traversal", "Path must not contain '..'.")
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise InvalidLogicalPath("segment_too_long", "A path segment is too long.")
        if segment != segment.rstrip(" ."):
            # Windows strips these on creation, so `report ` and `report` become
            # the same directory there. Refuse rather than silently rewrite.
            raise InvalidLogicalPath(
                "trailing_dot_or_space",
                "A path segment must not end with a dot or a space.",
            )
        stem = segment.split(".", 1)[0].lower()
        if stem in _RESERVED_STEMS:
            raise InvalidLogicalPath("reserved_name", "A path segment uses a reserved device name.")
        segments.append(segment)

    if len(segments) > MAX_DEPTH:
        raise InvalidLogicalPath("too_deep", "Path has too many levels.")

    return "/".join(segments)


def collision_key(normalized_path: str, export_filename: str) -> str:
    """The key two entries must not share.

    Case-folded and NFKC-normalised, because the question is not "are these the
    same string" but "will these be the same file after extraction". macOS and
    Windows are case-insensitive; NFKC folds compatibility spellings that render
    identically. Answering the easier question is how two entries silently
    overwrite each other inside a ZIP.

    `casefold()` rather than `lower()`: `lower()` leaves the German sharp s
    alone, so `STRASSE` and `straße` would compare unequal here and collide on
    disk.
    """
    joined = f"{normalized_path}/{export_filename}" if normalized_path else export_filename
    return unicodedata.normalize("NFKC", joined).casefold()


def sanitize_export_filename(raw: str, *, fallback: str) -> str:
    """A filesystem-safe filename for the archive.

    The uploaded filename is never trusted as a path component. It arrives from
    outside, it has already served its purpose as metadata, and the only thing
    needed here is a name that cannot escape a directory or shadow a device.
    Anything unsafe is replaced rather than refused, because a package must not
    become un-exportable over a character in a filename somebody uploaded a year
    ago -- and `fallback` guarantees a name even when nothing survives.
    """
    value = unicodedata.normalize("NFC", str(raw or "")).strip()
    value = value.replace("\\", "/").rsplit("/", 1)[-1]  # basename only
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "._- ()[]") else "_"
        for ch in value
        if ord(ch) >= 32 and ord(ch) != 127
    ).strip(" .")

    if not cleaned:
        return fallback
    if cleaned.split(".", 1)[0].lower() in _RESERVED_STEMS:
        cleaned = f"_{cleaned}"
    if len(cleaned) > MAX_SEGMENT_LENGTH:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) < 20:
            keep = MAX_SEGMENT_LENGTH - len(ext) - 1
            cleaned = f"{stem[:keep]}.{ext}"
        else:
            cleaned = cleaned[:MAX_SEGMENT_LENGTH]
    return cleaned or fallback
