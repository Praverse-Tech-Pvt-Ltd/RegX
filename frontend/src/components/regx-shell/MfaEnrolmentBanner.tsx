"use client";

import { useEffect, useState } from "react";
import { mfa } from "@/lib/api";

/**
 * SOW 4.3: a Reviewer, VP, Tenant Admin or Platform Support user with no MFA
 * device can read but not act (backend setting REGX_MFA_REQUIRED_ROLES).
 *
 * The backend refuses their state-changing requests with 403
 * `mfa_enrolment_required`; this banner tells them why before they try, and
 * links to the enrolment screen. If the status call fails, nothing is shown:
 * the backend still enforces the rule.
 */
export default function MfaEnrolmentBanner() {
  const [required, setRequired] = useState(false);

  useEffect(() => {
    let live = true;
    mfa
      .status()
      .then((s) => {
        if (live) setRequired(s.mfa_enrolment_required);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  if (!required) return null;
  return (
    <div
      role="alert"
      style={{
        margin: "1rem",
        padding: "0.75rem 1rem",
        border: "1px solid #c9a227",
        borderRadius: 6,
        background: "#fff8e1",
        color: "#3d3200",
      }}
    >
      Your role requires two-step sign-in (MFA). You can view
      records, but you cannot review, approve or change anything until you{" "}
      <a href="/mfa/setup">set up MFA</a>.
    </div>
  );
}
