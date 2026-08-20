/*
 * The company mark is a raster asset served from /regx-shell/, matching how
 * CompanyNavbar.tsx loads it. next/image would demand a configured loader for
 * what is a fixed-size logo in the public dir.
 */
/* eslint-disable @next/next/no-img-element */

import type { ReactNode } from "react";

/**
 * Shared chrome for the unauthenticated screens.
 *
 * Sign-in and MFA are the only two pages a user meets before the application
 * shell exists, and they were the two rendering as raw HTML. Putting the
 * branding, panel and card here means the pair cannot drift apart, and any
 * later auth screen inherits the same treatment for free.
 *
 * The left panel is decorative and marked aria-hidden: it repeats no
 * information the form does not already carry, so a screen reader should not
 * have to walk it before reaching the fields.
 */
export default function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="regx-auth">
      <aside className="regx-auth__brand" aria-hidden="true">
        {/* No logo here on purpose: the mark is dark-on-light, and inverting
            it for the navy panel flattened its anti-aliasing into a ghosted
            blob. It sits on the light card instead, at the navbar's own
            dimensions, where it needs no filtering. */}
        <div className="regx-auth__brand-body">
          <span className="regx-auth__eyebrow">Regulatory Intelligence</span>
          <p className="regx-auth__brand-title">
            The secure <em>RegX</em> workspace for regulatory teams
          </p>
          <p className="regx-auth__brand-text">
            Documents, formulations, assessments and review workflows — governed,
            tenant-scoped and fully audited.
          </p>
        </div>

        <ul className="regx-auth__points">
          <li>Tenant-isolated by design</li>
          <li>Every action recorded to an append-only audit trail</li>
          <li>Role-based access across every module</li>
        </ul>
      </aside>

      <main className="regx-auth__panel">
        <div className="regx-auth__card">
          <img
            src="/regx-shell/itechnical-logo.png"
            alt="iPharmaAI"
            className="regx-auth__card-logo"
          />
          <h1 className="regx-auth__title">{title}</h1>
          {subtitle ? <p className="regx-auth__subtitle">{subtitle}</p> : null}
          {children}
          {footer ? <div className="regx-auth__foot">{footer}</div> : null}
        </div>
      </main>
    </div>
  );
}
