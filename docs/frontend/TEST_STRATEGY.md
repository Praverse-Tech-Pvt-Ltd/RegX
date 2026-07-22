# Frontend Test Strategy

## Layers

| Layer | Tool | What it covers |
|---|---|---|
| Type safety | TypeScript strict | Compile-time correctness |
| Lint | ESLint (next/core-web-vitals) | Code quality |
| E2E | Playwright | Golden path user flows, accessibility |

## E2E tests

Located in `frontend/e2e/`.

| File | Covers |
|---|---|
| `signin.spec.ts` | Sign-in form rendering, error on bad creds, accessible labels |

## Accessibility baseline

Every page must have accessible form labels, ARIA roles on error messages, and keyboard navigation support. See `ACCESSIBILITY_BASELINE.md`.

## Running

```bash
cd frontend
npm run test:e2e
```
