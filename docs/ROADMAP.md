# REGX Roadmap / Handover

Tracks milestone status on the `regx-main` line. This branch is a clean-room implementation and shares no code with the legacy booking demo on `main` — see [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md).

## Milestone 3 — Regulatory Template Migration and Governance Foundation

**Milestone 3 technical framework: COMPLETE**
**Production regulatory-template migration: NOT STARTED**

Canonical `templates_registry` domain, staged import pipeline, non-destructive
normalization, deterministic duplicate-candidate reconciliation, a full
approval lifecycle (draft → review → approve/reject/return → activate →
supersede/retire), tenant isolation, segregation of duties, JSON/CSV
reconciliation exports, and governance APIs/frontend. This is the migration
and governance **framework** only — no real client regulatory template
content has been imported, reviewed, approved, or activated. See
[TEMPLATE_GOVERNANCE.md](TEMPLATE_GOVERNANCE.md) for architecture and the
other `TEMPLATE_*.md` docs for the import pipeline, normalization, duplicate
reconciliation, approval lifecycle, reconciliation reports, and test
strategy.

### Record

- **PR:** [#3](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/3)
- **Source SHA:** `27d38cb6e6d1c4bb893c943ce036d37b9e91f352`
- **Merge SHA:** `37a58ce9149d47e55823ef15a40f53a19f64f08e` (two-parent merge commit into `regx-main`, not squashed)
- **Release tag:** [`regx-template-governance-v0.3.0`](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/releases/tag/regx-template-governance-v0.3.0), on the merge commit
- **Legacy `main`:** unchanged throughout (`8ed8cf4b79262c1f3f261e872dc387783818e9ed`)

### Human review

- **First review gate:** identified 1 Critical (cross-tenant duplicate-candidate mutation in `MigrationBatchReviewView`) and 1 Major (CSV/formula-injection in reconciliation exports) finding, plus 2 Minor findings (concurrent version-number allocation race, incomplete audit metadata). Result: FAIL.
- **Remediation:** all four findings fixed with 25 new regression tests. Cross-tenant candidate resolution is now scoped through a shared `duplicate_candidates_for_source_package()` helper with atomic all-or-nothing bulk review; CSV exports are neutralized against formula injection at render time (raw DB values untouched); version-number allocation is now lock-serialized with a bounded retry; duplicate-resolution and reconciliation-export audit events now carry full decision detail.
- **Second review gate:** PASS — no Critical or Major findings remained. One non-blocking documentation gap noted (CSV export-safety and `RECONCILIATION_EXPORTED` event not yet documented).
- **Documentation closure:** PASS — `TEMPLATE_RECONCILIATION_REPORT.md` and `TEMPLATE_DUPLICATE_RECONCILIATION.md` updated to close the gap.

### CI (post-merge, on `regx-main` at the merge commit)

- [Backend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420018) — success
- [Frontend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420025) — success
- [Docker Integration](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420031) — success

### Test counts

- **Backend:** 268 tests passed (99 in `templates_registry`, including tenant-isolation, CSV-security, concurrency, audit, and 10 planted-failure scenarios), 92.01% coverage (gate 55%). Ruff lint/format clean, import-linter 4/4 contracts kept, OpenAPI generates and validates, AIDatabase guard clean, 483/warning-letter guard clean.
- **Frontend unit/accessibility:** 32 tests (Vitest + React Testing Library + jest-axe), including 10 accessibility checks.
- **Frontend Playwright:** 34 tests, including the migration-governance flow suite (template lifecycle actions, migration batch list/detail, reconciliation permission gating, duplicate-candidate resolution).

### Known limitations

1. Only synthetic, non-confidential fixtures are included — no real client regulatory template package has been imported.
2. Source ownership and licensing for any future real client source package remain to be confirmed before import.
3. Production regulatory-approver (VP/Tenant Admin) role assignments for real tenants remain to be defined by the client organization.
4. No checklist-execution engine exists — this milestone is governance/migration only.
5. No IIG calculations exist. `TemplateItem.applicability_rule` is a reserved placeholder field only; no evaluation logic exists.
6. No Orange Book integration exists.
7. No AI summarization or chatbot exists.
8. No Word add-in exists.
9. No 21 CFR Part 11 compliance is claimed by this milestone.
10. Production malware scanning still requires an actual scanner deployment (carried over from Milestone 2 — `StubScanner` marks all files clean; `ClamAVScanner` needs a running clamd service not part of this milestone's compose stack).
11. S3-compatible storage remains an integration point only (carried over from Milestone 2 — `LocalStorage` is what's exercised end-to-end).
12. The Docker Integration CI workflow verifies clean stack startup and migrations; it does not automate a complete real-template-package migration cycle end to end.

---

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

Milestone 4 has not been planned or started. Production regulatory-template
migration (importing, reviewing, approving, and activating a real client
source package) is not started and requires a client-approved source
package plus confirmed ownership/licensing before it can begin. No
checklist-execution engine, IIG automation, calculators, Orange Book,
ANDA/DMF scoring, regulatory AI, report generation, or Word integration
work has begun.
