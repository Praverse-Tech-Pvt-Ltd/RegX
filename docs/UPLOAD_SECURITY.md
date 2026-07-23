# Upload Security

## Validation pipeline

Every file upload passes through `documents.validators.validate_upload()` before storage. The checks run in order:

1. **Filename guards** (`validate_filename`)
   - Empty filename rejected
   - Path traversal (`..`, `/`, `\`, null byte) checked on raw filename before `os.path.basename`
   - Executable extensions (`.exe`, `.sh`, `.bat`, `.ps1`, etc.) rejected
   - Macro-enabled Office extensions (`.docm`, `.xlsm`, `.pptm`, etc.) rejected
   - Double-extension bypass (e.g. `evil.exe.pdf`) detected via two-extension check
   - Disallowed extension (only pdf/docx/xlsx/pptx allowed)

2. **File size guards**
   - Empty file rejected
   - File exceeding `DOCUMENT_MAX_UPLOAD_BYTES` (default 50 MB) rejected

3. **MIME validation**
   - Declared MIME must be in the allowlist
   - Declared MIME must match the file extension
   - Magic bytes checked via `filetype` library; must match declared MIME

4. **Office container inspection** (docx/xlsx/pptx only)
   - Must be a valid ZIP archive (`zipfile.BadZipFile` → rejected)
   - Entry count must not exceed 1000 (ZIP bomb guard)
   - Uncompressed total size must not exceed 512 MB (decompression bomb guard)
   - No nested ZIP archives inside the container
   - `[Content_Types].xml` must be present and contain the expected content-type marker
   - `vbaProject.bin` presence → macro content → rejected

5. **XLSX dimension check** (xlsx only)
   - Row count must not exceed 1,048,576
   - Column count must not exceed 16,384

## Error codes

All validation errors surface a `safe_code` and `safe_message` that are forwarded to the API response as HTTP 422. Internal error details (file paths, stack traces) are never included.

| Code | Trigger |
|---|---|
| `empty_filename` | No filename provided |
| `path_traversal` | `..`, `/`, `\`, or null byte in raw filename |
| `executable_extension` | Executable file extension |
| `macro_extension` | Macro-enabled Office extension |
| `double_extension` | Executable extension hidden before allowed extension |
| `disallowed_extension` | Extension not in pdf/docx/xlsx/pptx allowlist |
| `empty_file` | Zero-byte file |
| `file_too_large` | Exceeds `DOCUMENT_MAX_UPLOAD_BYTES` |
| `disallowed_mime` | Declared MIME not in allowlist |
| `mime_extension_mismatch` | MIME and extension do not agree |
| `mime_signature_mismatch` | Magic bytes do not match declared MIME |
| `invalid_office_container` | Not a valid ZIP archive |
| `zip_bomb` | Too many entries or excessive uncompressed size |
| `nested_archive` | ZIP inside ZIP |
| `missing_content_types` | `[Content_Types].xml` absent |
| `office_format_mismatch` | Content type marker missing for declared extension |
| `macro_content` | `vbaProject.bin` found in container |
| `corrupt_office_container` | `BadZipFile` during inspection |
| `xlsx_row_limit` | Exceeds row limit |
| `xlsx_column_limit` | Exceeds column limit |
