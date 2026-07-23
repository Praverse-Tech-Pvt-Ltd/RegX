# REGX Roadmap / Handover

Tracks milestone status on the `regx-main` line. This branch is a clean-room implementation and shares no code with the legacy booking demo on `main` — see [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md).

## Milestone 2 — Secure Document Platform Foundation

**Status: COMPLETE**

Tenant-scoped document upload, malware-scan gating, format-specific processing (PDF/DOCX/XLSX/PPTX), and versioning, with a Next.js frontend on a hardened Django/DRF backend. See [DOCUMENT_PLATFORM.md](DOCUMENT_PLATFORM.md) for architecture.

### Record

- **PR:** [#1](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/1)
- **Source SHA:** `a25dc743f9281025b6cd4928dde2003261475cfb`
- **Merge SHA:** `7a749c852ab0cec42e6eabcaa59932fe0549b668` (two-parent merge commit into `regx-main`, not squashed)
- **Release tag:** [`regx-document-platform-v0.2.0`](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/releases/tag/regx-document-platform-v0.2.0), on the merge commit
- **Legacy `main`:** unchanged throughout (`8ed8cf4b79262c1f3f261e872dc387783818e9ed`)

### CI (post-merge, on `regx-main` at the merge commit)

- [Backend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493597) — success
- [Frontend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493644) — success
- [Docker Integration](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493605) — success

### Test counts

- **Backend:** 169 tests passed, 90.15% coverage (gate 55%). Ruff lint/format clean, import-linter 3/3 contracts kept, AIDatabase guard clean.
- **Frontend unit/accessibility:** 25 tests (Vitest + React Testing Library + jest-axe) — no serious/critical automated a11y violations on `/signin`, `/documents`, `/documents/{id}`.
- **Frontend Playwright:** 24 tests (18 document-flow, 3 sign-in, 2 security/storage, 1 CSP-hydration regression guard).

### Known limitations

1. Production malware scanning requires a real scanner deployment — the shipped `StubScanner` marks all files clean and is explicitly logged as unsafe for production; `ClamAVScanner` exists as the real backend but needs a running clamd service, which is not part of this milestone's compose stack.
2. S3-compatible storage is an abstraction/integration point only — `LocalStorage` is the storage backend actually exercised end-to-end; `S3CompatibleStorage` is scaffolded but not verified against a real S3-compatible endpoint.
3. The Docker Integration CI workflow does not yet automate the complete synthetic PDF upload → scan → processing → locator-creation cycle. That full pipeline was verified manually against the live compose stack during closure, not by a repeatable, automated CI step.
4. Electronic signatures and 21 CFR Part 11 validation are **not implemented**. No claim of Part 11 compliance is made by this milestone.
5. OCR is not implemented.
6. Document comparison and AI summaries are not implemented.

---

## Milestone 1 — REGX Foundation

Branch and tenancy/identity/authorization/audit foundation preceding the document platform. See prior commits on `regx-main` for detail; not re-summarized here.

---

## Next

Milestone 3 has not been planned or started. No checklist migration, IIG automation, calculators, Orange Book, ANDA/DMF scoring, regulatory AI, report generation, or Word integration work has begun.
