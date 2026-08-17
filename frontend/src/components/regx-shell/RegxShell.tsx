"use client";

import { useState } from "react";
import CompanyNavbar from "./CompanyNavbar";
import RegxSidebar from "./RegxSidebar";

/**
 * The company /ratools/ shell, reproduced for the REGX operational pages.
 *
 * The element tree mirrors the <body> of
 * company_site/templates/RATools/RAToolsBase.html:
 *
 *   .tt-shell
 *     navbar.html                                  -> <CompanyNavbar/>
 *     .container-fluid.page-body-wrapper
 *      .dashboard-page-body.dashboard-layout       -> collapse target
 *       nav.dashboard-sidebar                      -> <RegxSidebar/>
 *       .main-panel.dashboard-main-panel
 *         .content-wrapper                         -> {children}
 *
 * The inline styles below are copied from the template rather than moved into
 * a stylesheet, because the collapsed rules in regx-shell.css override them
 * with !important exactly as they do in the original — reproducing the same
 * cascade is what makes the 270px -> 96px transition behave identically.
 *
 * Per Phase 10 the marketing hero is deliberately absent here: it belongs to
 * the /ratools/ landing, which the company site still renders itself.
 */
export default function RegxShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="tt-shell">
      <CompanyNavbar />

      <div
        className={`container-fluid page-body-wrapper dashboard-page-body dashboard-layout${
          collapsed ? " sidebar-collapsed" : ""
        }`}
        id="dashboardLayout"
      >
        <RegxSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
        />

        <div
          className="main-panel dashboard-main-panel"
          style={{
            marginLeft: "270px",
            transition: "margin-left 0.3s ease, width 0.3s ease",
          }}
        >
          <div
            className="content-wrapper"
            style={{
              padding: 0,
              background: "transparent",
              display: "flex",
              flexDirection: "column",
              minHeight: "calc(100vh - 70px)",
              flexGrow: 1,
            }}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
