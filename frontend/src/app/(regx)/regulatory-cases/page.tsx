"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { regulatoryCases, ApiError, type CasePermissions, type CaseStatus, type RegulatoryCase, isSignedOut, loadError } from "@/lib/api";
import { CaseStatusBadge } from "./status-badge";

const STATUS_FILTERS: Array<{ value: "" | CaseStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "open", label: "Open" },
  { value: "on_hold", label: "On hold" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
  navy: "#003865",
} as const;

const cell: React.CSSProperties = {
  padding: "0.6rem 0.5rem",
  fontSize: "0.9rem",
  color: T.text,
  verticalAlign: "middle",
};

const head: React.CSSProperties = {
  padding: "0.5rem",
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  color: T.muted,
};

const field: React.CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.88rem",
};

const EMPTY_FORM = {
  title: "",
  product_name: "",
  market: "",
  submission_type: "",
  product_code: "",
  authority: "",
  target_date: "",
};

function CasesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [cases, setCases] = useState<RegulatoryCase[]>([]);
  const [permissions, setPermissions] = useState<CasePermissions | null>(null);
  const [statusFilter, setStatusFilter] = useState<"" | CaseStatus>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [busy, setBusy] = useState(false);

  function load(filter: "" | CaseStatus, term: string) {
    if (!tenantSlug) return Promise.resolve();
    setLoading(true);
    return regulatoryCases
      .list(tenantSlug, {
        ...(filter ? { status: filter } : {}),
        ...(term ? { search: term } : {}),
      })
      .then((resp) => {
        setCases(resp.results);
        setPermissions(resp.permissions);
        setError(null);
      })
      .catch((err: unknown) => {
        if (isSignedOut(err)) {
          router.push(
            `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
          );
        } else {
          setError(loadError(err, "Failed to load regulatory cases."));
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    void load(statusFilter, search);
  }, [tenantSlug, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await regulatoryCases.create(tenantSlug, {
        title: form.title.trim(),
        product_name: form.product_name.trim(),
        market: form.market.trim(),
        submission_type: form.submission_type.trim(),
        product_code: form.product_code.trim(),
        authority: form.authority.trim(),
        target_date: form.target_date || null,
      });
      router.push(`/regulatory-cases/${created.public_id}?tenant=${tenantSlug}`);
    } catch (err: unknown) {
      // Reload FIRST, then set the message: `load()` clears the error on a
      // successful fetch, so setting it beforehand would wipe it.
      await load(statusFilter, search);
      if (err instanceof ApiError && err.status === 400) {
        setError("Check the required fields and try again.");
      } else if (err instanceof ApiError && err.status === 403) {
        setError("You do not have permission to create cases in this tenant.");
      } else {
        setError("Could not create the case.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!tenantSlug) return null;

  const canCreate = permissions?.can_create ?? false;
  const createReady =
    form.title.trim() && form.product_name.trim() && form.market.trim() && form.submission_type.trim();

  return (
    <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
          marginBottom: "1.25rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.6rem", fontWeight: 700, color: T.ink }}>
          Regulatory Cases
        </h1>
        {/* Advisory only: the API re-checks on every call. */}
        {canCreate && (
          <button
            type="button"
            data-testid="new-case"
            onClick={() => setShowCreate((v) => !v)}
            style={{
              padding: "0.5rem 1rem",
              border: `1px solid ${T.navy}`,
              borderRadius: 8,
              background: T.blue,
              color: "#fff",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {showCreate ? "Close" : "New case"}
          </button>
        )}
      </div>

      {error && (
        <p
          role="alert"
          data-testid="cases-error"
          style={{
            margin: "0 0 1rem",
            padding: "0.6rem 0.8rem",
            border: "1px solid #f3c9c4",
            borderRadius: 6,
            background: "#fdf3f2",
            color: "#8f2c20",
            fontSize: "0.88rem",
          }}
        >
          {error}
        </p>
      )}

      {showCreate && canCreate && (
        <form
          onSubmit={handleCreate}
          data-testid="create-case-form"
          aria-label="Create case form"
          style={{
            marginBottom: "1.25rem",
            padding: "1rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
            display: "grid",
            gap: "0.6rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
          }}
        >
          {(
            [
              ["title", "Title", true],
              ["product_name", "Product / API", true],
              ["market", "Market", true],
              ["submission_type", "Submission type", true],
              ["product_code", "Product code", false],
              ["authority", "Authority", false],
            ] as const
          ).map(([name, label, required]) => (
            <label key={name} style={{ display: "grid", gap: 4, fontSize: "0.8rem", color: T.ink }}>
              {label}
              {required ? " *" : ""}
              <input
                data-testid={`case-${name}`}
                value={form[name]}
                onChange={(e) => setForm({ ...form, [name]: e.target.value })}
                style={field}
              />
            </label>
          ))}
          <label style={{ display: "grid", gap: 4, fontSize: "0.8rem", color: T.ink }}>
            Target date
            <input
              type="date"
              data-testid="case-target_date"
              value={form.target_date}
              onChange={(e) => setForm({ ...form, target_date: e.target.value })}
              style={field}
            />
          </label>
          <div style={{ display: "flex", alignItems: "end" }}>
            <button
              type="submit"
              data-testid="create-case-submit"
              disabled={busy || !createReady}
              style={{
                padding: "0.5rem 1rem",
                border: `1px solid ${busy || !createReady ? T.line : T.navy}`,
                borderRadius: 8,
                background: busy || !createReady ? T.soft : T.blue,
                color: busy || !createReady ? T.muted : "#fff",
                fontWeight: 600,
                cursor: busy || !createReady ? "not-allowed" : "pointer",
              }}
            >
              Create case
            </button>
          </div>
        </form>
      )}

      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap" }}>
        <label style={{ fontSize: "0.85rem", color: T.muted }}>
          Status{" "}
          <select
            data-testid="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | CaseStatus)}
            style={field}
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void load(statusFilter, search);
          }}
          style={{ display: "flex", gap: "0.4rem" }}
          role="search"
        >
          <label htmlFor="case-search" style={{ position: "absolute", left: -9999 }}>
            Search cases
          </label>
          <input
            id="case-search"
            data-testid="case-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search cases"
            style={{ ...field, minWidth: 220 }}
          />
          <button
            type="submit"
            data-testid="case-search-submit"
            style={{
              padding: "0.45rem 0.9rem",
              border: `1px solid ${T.line}`,
              borderRadius: 6,
              background: "#fff",
              color: T.blue,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Search
          </button>
        </form>
      </div>

      {loading && <p style={{ color: T.muted }}>Loading cases…</p>}

      {!loading && cases.length === 0 && (
        <p
          data-testid="cases-empty"
          style={{
            margin: 0,
            padding: "1.5rem 1rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
            color: T.muted,
            fontSize: "0.9rem",
          }}
        >
          No regulatory cases yet.
        </p>
      )}

      {!loading && cases.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            data-testid="cases-table"
            style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}
          >
            <thead>
              <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
                <th style={head}>Case</th>
                <th style={head}>Title</th>
                <th style={head}>Product / API</th>
                <th style={head}>Market</th>
                <th style={head}>Submission type</th>
                <th style={head}>Owner</th>
                <th style={head}>Target date</th>
                <th style={head}>Status</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.public_id} style={{ borderBottom: `1px solid ${T.line}` }}>
                  <td style={{ ...cell, whiteSpace: "nowrap", fontWeight: 600 }}>
                    <Link
                      href={`/regulatory-cases/${c.public_id}?tenant=${tenantSlug}`}
                      data-testid="case-link"
                    >
                      {c.case_number}
                    </Link>
                  </td>
                  <td style={cell}>{c.title}</td>
                  <td style={cell}>{c.product_name}</td>
                  <td style={cell}>{c.market}</td>
                  <td style={cell}>{c.submission_type}</td>
                  <td style={{ ...cell, color: c.owner ? T.text : T.muted }}>
                    {c.owner ? c.owner.full_name : "—"}
                  </td>
                  <td style={{ ...cell, color: c.target_date ? T.text : T.muted }}>
                    {c.target_date ? new Date(c.target_date).toLocaleDateString() : "—"}
                  </td>
                  <td style={cell}>
                    <CaseStatusBadge status={c.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

export default function RegulatoryCasesPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <CasesPageInner />
    </Suspense>
  );
}
