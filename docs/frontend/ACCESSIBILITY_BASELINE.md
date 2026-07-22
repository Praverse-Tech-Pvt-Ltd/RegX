# Accessibility Baseline

## Requirements

- All form inputs have associated `<label>` elements with matching `htmlFor` / `id`.
- Error messages use `role="alert"` so screen readers announce them immediately.
- Interactive elements are reachable and operable via keyboard (`Tab`, `Enter`, `Space`).
- Buttons have descriptive text (no icon-only buttons without `aria-label`).
- Color is not the sole conveyor of information.
- Pages have a single `<h1>` heading.

## Enforcement

- Playwright E2E tests verify label associations and ARIA roles on sign-in and MFA pages.
- TypeScript strict mode prevents missing `id` / `htmlFor` props from being silently undefined.

## Future

axe-playwright integration for automated WCAG 2.1 AA scanning.
