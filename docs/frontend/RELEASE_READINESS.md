# Frontend Release Readiness

## Checklist

### Build
- [ ] `npm run type-check` passes with zero errors
- [ ] `npm run lint` passes
- [ ] `npm run build` succeeds

### Tests
- [ ] All E2E tests pass in CI
- [ ] No console errors on sign-in, MFA, tenants, and dashboard pages

### Security
- [ ] No auth token in localStorage or sessionStorage
- [ ] CSP headers present: `frame-ancestors 'none'`, `object-src 'none'`, `script-src 'self'`
- [ ] `X-Frame-Options: DENY` header present
- [ ] `X-Content-Type-Options: nosniff` header present

### Accessibility
- [ ] All form inputs have labels
- [ ] Error messages use `role="alert"`
- [ ] Keyboard navigation works on all interactive elements

### Performance
- [ ] No unoptimised images (use `next/image`)
- [ ] No synchronous client-side data fetches blocking render
