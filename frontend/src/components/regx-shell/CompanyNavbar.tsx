"use client";

/*
 * Every destination in this navbar is a company Django page, not a Next.js
 * route, so all of them are plain <a> elements: a next/link would client-side
 * navigate inside the React app and never reach the company site. The `/`
 * entry is the sharp case — Next.js also has a root page, so the linter
 * assumes Link is meant, when a full document load is exactly what we need.
 *
 * <img> is likewise deliberate: this is a port of navbar.html, and next/image
 * would change the emitted markup and break the company CSS that targets
 * these elements.
 */
/* eslint-disable @next/next/no-html-link-for-pages, @next/next/no-img-element */

import { usePathname } from "next/navigation";
import { useState } from "react";

/**
 * Port of company_site/templates/navbar.html.
 *
 * The markup and class names mirror the Django template one-for-one so that
 * the extracted company-navbar.css applies unchanged and the navbar is
 * pixel-identical to the one rendered either side of these pages by the
 * company site (notably on /ratools/, the RegX landing).
 *
 * Two deliberate differences from the template, both behavioural rather than
 * visual:
 *   * the mobile toggle is React state rather than Bootstrap's collapse JS,
 *     so the frontend needs neither jQuery nor an inline-script CSP hole;
 *   * the authenticated branch reflects REGX identity, not the company's
 *     CustomUser, because these pages are governed by REGX auth.
 */

const NAV_LINKS = [
  {
    href: "/aidatabase/auditiq/",
    label: "Audit IQ",
    icon: "/company/assets-icretegy-483.png",
    matches: ["/aidatabase/"],
  },
  {
    href: "/ratools/modulehome/",
    label: "ANDA CTD SmartTemplate",
    icon: "/company/assets-anda-ctd.svg",
    matches: ["/ratools/modulehome/"],
  },
  {
    href: "/ratools/",
    label: "RegX",
    icon: "/company/assets-icretegy-tools.png",
    matches: [],
  },
];

/** Operational prefixes that live inside the RegX area of the site. */
const REGX_AREA_PREFIXES = [
  "/documents",
  "/fda-data",
  "/formulations",
  "/iid-assessments",
  "/iig-checklists",
  "/migration-batches",
  "/templates",
  "/template-sources",
  "/tenants",
  "/dashboard",
];

export default function CompanyNavbar() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);

  // Every operational page sits under the company's "RegX" nav entry, so that
  // entry stays lit while the user works inside the module pages.
  const inRegxArea = REGX_AREA_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );

  return (
    <nav className="navbar navbar-expand-lg custom-navbar fixed-top">
      <div className="container-fluid px-4">
        <a className="navbar-brand" href="/">
          <img
            src="/company/itechnical-logo.png"
            alt="logo"
            className="navbar-logo"
            style={{ width: "145px", maxWidth: "100%", height: "auto" }}
          />
        </a>

        <button
          className="navbar-toggler border-0 shadow-none"
          type="button"
          aria-controls="mainNavbar"
          aria-expanded={open}
          aria-label="Toggle navigation"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="navbar-toggler-icon" />
        </button>

        <div
          className={`collapse navbar-collapse${open ? " show" : ""}`}
          id="mainNavbar"
        >
          <ul className="navbar-nav mx-auto align-items-lg-center gap-lg-2">
            {NAV_LINKS.map((link) => {
              const active =
                link.href === "/ratools/"
                  ? inRegxArea
                  : link.matches.some((m) => pathname.startsWith(m));
              return (
                <li className="nav-item" key={link.href}>
                  <a
                    className={`nav-link custom-nav-link${active ? " active-nav" : ""}`}
                    href={link.href}
                  >
                    <img
                      src={link.icon}
                      alt=""
                      style={{
                        width: "20px",
                        height: "auto",
                        mixBlendMode: "darken",
                      }}
                    />
                    <span className="ms-1">{link.label}</span>
                  </a>
                </li>
              );
            })}
          </ul>

          <div className="d-flex align-items-center gap-3 mt-4 mt-lg-0 ms-lg-auto">
            <a href="/adminmaster/login/" className="login-btn">
              Login
            </a>
            <a href="/ratools/requestdemo" className="demo-btn">
              Schedule Consultation
            </a>
          </div>
        </div>
      </div>
    </nav>
  );
}
