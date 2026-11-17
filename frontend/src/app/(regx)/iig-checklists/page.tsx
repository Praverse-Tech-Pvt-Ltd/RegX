"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { iigChecklists, type ChecklistDefinition, isSignedOut, loadError } from "@/lib/api";

function DefinitionsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<ChecklistDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    iigChecklists.definitions
      .list(tenantSlug)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (isSignedOut(err)) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError(loadError(err, "Failed to load checklist definitions."));
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 960, margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Checklist Definitions</h1>
        <Link
          href={`/iig-checklists/new?tenant=${tenantSlug}`}
          style={{
            background: "#045e8f",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "8px 18px",
            cursor: "pointer",
            fontWeight: 600,
            textDecoration: "none",
            display: "inline-block",
          }}
        >
          New definition
        </Link>
      </div>

      <p style={{ fontSize: 13, color: "#66768b", marginTop: -8, marginBottom: "1rem" }}>
        This screen governs checklist definitions only — no checklist execution,
        responses, or calculation outcomes are shown or produced here.
      </p>

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#66768b" }}>No checklist definitions yet.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }} scope="col">
                Code
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Title
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Scope
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((def) => (
              <tr key={def.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 12 }}>
                  <Link
                    href={`/iig-checklists/${def.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#045e8f", textDecoration: "none" }}
                  >
                    {def.code}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>{def.title}</td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {def.scope_type.replace(/_/g, " ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function DefinitionsPage() {
  return (
    <Suspense>
      <DefinitionsPageInner />
    </Suspense>
  );
}
