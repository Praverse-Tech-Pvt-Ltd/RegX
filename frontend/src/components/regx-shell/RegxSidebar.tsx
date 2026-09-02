"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";

/**
 * Port of the sidebar in company_site/templates/RATools/RAToolsBase.html.
 *
 * Class names, DOM shape, icons and `data-tooltip` attributes match the
 * template exactly, so the extracted regx-shell.css drives the 270px ->
 * 96px collapse, the icon-only state and the hover tooltips with no
 * hand-written styling.
 *
 * Bootstrap's collapse JS is replaced by React state for the same reason as
 * in CompanyNavbar: no jQuery, no inline-script CSP hole.
 *
 * Two groups are listed, and both are real:
 *   * REGX PLATFORM  — the modules built in this project, served by Next.js
 *     against the REGX API.
 *   * REGULATORY TOOLS — the company's own legacy tools, linking to the
 *     company site that now runs alongside us. These are live pages, not
 *     placeholders; nothing here advertises functionality that does not
 *     exist.
 */

type Child = { href: string; label: string };
type Item = {
  id: string;
  href?: string;
  label: string;
  icon: string;
  children?: Child[];
  external?: boolean;
};

const REGX_MODULES: Item[] = [
  {
    id: "documents",
    href: "/documents",
    label: "Documents",
    icon: "mdi mdi-file-document-outline",
  },
  {
    id: "fda-data",
    label: "FDA Data",
    icon: "mdi mdi-database-outline",
    children: [
      { href: "/fda-data/releases", label: "Source Releases" },
      { href: "/fda-data/mappings", label: "Terminology Mappings" },
      { href: "/fda-data/orange-book", label: "Orange Book" },
    ],
  },
  {
    id: "formulations",
    href: "/formulations",
    label: "Formulations",
    icon: "mdi mdi-flask-empty-outline",
  },
  {
    // There is no /iid-assessments index route — the module exposes a preview
    // screen and per-assessment detail pages only, so linking the bare path
    // would be a 404 in the sidebar. Caught by the shell E2E asset check.
    id: "iid-assessments",
    href: "/iid-assessments/preview",
    label: "IID Assessments",
    icon: "mdi mdi-clipboard-text-outline",
  },
  {
    id: "iig-checklists",
    label: "IIG Checklists",
    icon: "mdi mdi-checkbox-marked-outline",
    children: [
      { href: "/iig-checklists", label: "Definitions" },
      { href: "/iig-checklists/versions", label: "Versions" },
      { href: "/iig-checklists/executions", label: "Executions" },
    ],
  },
  {
    id: "regulatory-cases",
    href: "/regulatory-cases",
    label: "Regulatory Cases",
    icon: "mdi mdi-folder-open-outline",
  },
  {
    id: "workflows",
    href: "/workflows",
    label: "Workflows",
    icon: "mdi mdi-sitemap",
  },
  {
    id: "migration-batches",
    href: "/migration-batches",
    label: "Migration Batches",
    icon: "mdi mdi-swap-horizontal",
  },
  {
    id: "external-integrations",
    href: "/external-integrations",
    label: "External Integrations",
    icon: "mdi mdi-lan-connect",
  },
  {
    id: "templates",
    label: "Templates",
    icon: "mdi mdi-file-multiple-outline",
    children: [
      { href: "/templates", label: "Template Registry" },
      { href: "/template-sources", label: "Template Sources" },
    ],
  },
  {
    id: "tenants",
    href: "/tenants",
    label: "Tenants",
    icon: "mdi mdi-domain",
  },
];

/** Legacy company tools — served verbatim by the company_site container. */
const LEGACY_TOOLS: Item[] = [
  {
    id: "anda-review",
    label: "ANDA Review Checklist",
    icon: "mdi mdi-checkbox-marked-outline",
    external: true,
    children: [
      { href: "/ratools/show_anda_general_table", label: "General ANDA" },
      { href: "/ratools/show_anda_parenteral_dosage_table", label: "Parenteral Dosage" },
      { href: "/ratools/show_anda_solid_oral_dosage_table", label: "Solid Oral Dosage" },
      { href: "/ratools/show_anda_semi_solid_topical_dosage_table", label: "Semi Solid Topical Dosage" },
      { href: "/ratools/show_anda_ophthalmic_dosage_table", label: "Ophthalmic Dosage" },
      { href: "/ratools/show_anda_nasalspray_inhalation_table", label: "Nasal Spray & Inhalation" },
      { href: "/ratools/show_anda_mdi_and_dpi_table", label: "MDI & DPI" },
      { href: "/ratools/show_anda_transdermal_dosage_table", label: "Transdermal" },
      { href: "/ratools/show_anda_microsphere_table", label: "Microsphere" },
      { href: "/ratools/show_anda_liposome_table", label: "Liposome" },
    ],
  },
  {
    id: "white-paper",
    label: "White Paper (Strategic Paper)",
    icon: "mdi mdi-file-document-outline",
    external: true,
    children: [
      { href: "/ratools/general_white_paper_table", label: "General White Paper" },
    ],
  },
  {
    id: "controlled-corresp",
    label: "Controlled Correspondence",
    icon: "mdi mdi-email-outline",
    external: true,
    children: [
      { href: "/ratools/show_controlled_correspondences_template", label: "Template for Q1/Q2" },
      { href: "/ratools/show_controlled_correspondences_bestpractice", label: "Best Practice" },
    ],
  },
  {
    id: "dmf",
    href: "/ratools/show_dmf_table",
    label: "DMF Review Checklist",
    icon: "mdi mdi-clipboard-check-outline",
    external: true,
  },
  {
    id: "validation-checklist",
    label: "Validation Checklist",
    icon: "mdi mdi-cog-outline",
    external: true,
    children: [
      { href: "/ratools/show_drug_product_validation_table", label: "Drug Product Validation" },
      { href: "/ratools/show_api_validation_table", label: "API Validation" },
      { href: "/ratools/show_api_verification_table", label: "API Verification" },
    ],
  },
  {
    id: "anda-facility",
    href: "/ratools/show_anda_faciltiy",
    label: "ANDA Facility Template",
    icon: "mdi mdi-office-building-outline",
    external: true,
  },
  {
    id: "api-facility",
    href: "/ratools/show_api_faciltiy",
    label: "API Facility Template",
    icon: "mdi mdi-factory",
    external: true,
  },
  {
    id: "iig-clearance",
    label: "IIG Clearance Checklist",
    icon: "mdi mdi-flask-outline",
    external: true,
    children: [
      { href: "/ratools/show_iig_tablet_table", label: "Tablets & Capsules" },
      { href: "/ratools/show_iig_injection_table", label: "Injection" },
      { href: "/ratools/show_iig_liquidoral_table", label: "Liquid Orals" },
      { href: "/ratools/show_iig_topical_table", label: "Topical" },
      { href: "/ratools/show_iig_semisolid_table", label: "Semi Solids" },
      { href: "/ratools/show_iig_nasal_table", label: "Nasals" },
      { href: "/ratools/show_iig_inhalation_table", label: "Inhalation" },
      { href: "/ratools/show_iig_mdi_table", label: "MDI" },
      { href: "/ratools/show_iig_dpi", label: "DPI" },
      { href: "/ratools/show_iig_microsphere", label: "Microsphere" },
      { href: "/ratools/show_iig_liposome", label: "Liposome" },
      { href: "/ratools/show_iig_transdermal_table", label: "Transdermal" },
    ],
  },
  {
    id: "sss",
    href: "/ratools/show_sss",
    label: "Size Shape & Score",
    icon: "mdi mdi-ruler-square",
    external: true,
  },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/iid-assessments/preview") {
    // The entry points at the preview screen, but it represents the whole
    // module — so an assessment detail page must light it up too.
    return pathname.startsWith("/iid-assessments");
  }
  if (href === "/iig-checklists") {
    // The definitions list owns /iig-checklists itself and its [publicId]
    // and /new children, but not the sibling /versions and /executions
    // sections, which have their own entries.
    return (
      pathname === href ||
      (pathname.startsWith(`${href}/`) &&
        !pathname.startsWith("/iig-checklists/versions") &&
        !pathname.startsWith("/iig-checklists/executions"))
    );
  }
  if (href === "/templates") {
    return pathname === href || pathname.startsWith("/templates/");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function RegxSidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname() ?? "";

  const groupIsActive = (item: Item) =>
    item.children?.some((c) => isActive(pathname, c.href)) ?? false;

  const [open, setOpen] = useState<Record<string, boolean>>({});

  // Open the submenu that owns the current route on load and on navigation,
  // matching the company template, where the active section starts expanded.
  useEffect(() => {
    const owner = REGX_MODULES.find(
      (i) => i.children?.some((c) => isActive(pathname, c.href)),
    );
    if (owner) setOpen((prev) => ({ ...prev, [owner.id]: true }));
  }, [pathname]);

  const renderItem = (item: Item) => {
    const active = item.href ? isActive(pathname, item.href) : groupIsActive(item);

    if (!item.children) {
      const className = `dashboard-sidebar-link${active ? " active" : ""}`;
      const content = (
        <>
          <i className={`${item.icon} dashboard-sidebar-icon`} />
          <span className="dashboard-sidebar-label">{item.label}</span>
        </>
      );
      return (
        <li className="dashboard-sidebar-item" key={item.id}>
          {item.external ? (
            <a className={className} href={item.href} data-tooltip={item.label}>
              {content}
            </a>
          ) : (
            <Link
              className={className}
              href={item.href!}
              data-tooltip={item.label}
              aria-current={active ? "page" : undefined}
            >
              {content}
            </Link>
          )}
        </li>
      );
    }

    const expanded = open[item.id] ?? false;
    return (
      <li className="dashboard-sidebar-item" key={item.id}>
        <button
          type="button"
          className={`dashboard-sidebar-link d-flex justify-content-between align-items-center${
            active ? " active" : ""
          }`}
          data-tooltip={item.label}
          aria-expanded={expanded}
          aria-controls={item.id}
          onClick={() => setOpen((prev) => ({ ...prev, [item.id]: !expanded }))}
        >
          <div className="d-flex align-items-center">
            <i className={`${item.icon} dashboard-sidebar-icon`} />
            <span className="dashboard-sidebar-label">{item.label}</span>
          </div>
          <i className="mdi mdi-chevron-down" />
        </button>

        <div className={`collapse${expanded ? " show" : ""}`} id={item.id}>
          {item.children.map((child) =>
            item.external ? (
              <a
                className="dashboard-sidebar-link sub-sidebar-link"
                href={child.href}
                key={child.href}
              >
                {child.label}
              </a>
            ) : (
              <Link
                className={`dashboard-sidebar-link sub-sidebar-link${
                  isActive(pathname, child.href) ? " active" : ""
                }`}
                href={child.href}
                key={child.href}
                aria-current={isActive(pathname, child.href) ? "page" : undefined}
              >
                {child.label}
              </Link>
            ),
          )}
        </div>
      </li>
    );
  };

  return (
    <nav className="dashboard-sidebar" id="sidebar">
      <div className="dashboard-sidebar-inner">
        <div className="sidebar-toggle-row">
          <button
            type="button"
            className="sidebar-toggle-btn"
            id="sidebarToggle"
            onClick={onToggle}
            aria-expanded={!collapsed}
            aria-controls="sidebar"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <i className="mdi mdi-dock-left" />
          </button>
        </div>

        <div className="tt-sidebar-title">
          RegX Platform
          <span>Regulatory Operations</span>
        </div>

        <ul className="dashboard-sidebar-nav">{REGX_MODULES.map(renderItem)}</ul>

        <div className="tt-sidebar-title">
          Regulatory Tools
          <span>Company Suite</span>
        </div>

        <ul className="dashboard-sidebar-nav">{LEGACY_TOOLS.map(renderItem)}</ul>
      </div>
    </nav>
  );
}
