"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { tenants, type Tenant, ApiError } from "@/lib/api";

export default function TenantsPage() {
  const router = useRouter();
  const [items, setItems] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    tenants
      .list()
      .then(setItems)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load tenants.");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) return <p>Loading...</p>;
  if (error) return <p role="alert">{error}</p>;

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Your organisations</h1>
      <p>Choose an organisation to open its workspace.</p>
      {items.length === 0 ? (
        <p>No organisations found.</p>
      ) : (
        <ul>
          {items.map((t) => (
            <li key={t.id}>
              {/* Every REGX page reads its tenant from ?tenant=, so choosing an
                  organisation means entering REGX with it set. */}
              <Link href={`/dashboard?tenant=${encodeURIComponent(t.slug)}`}>
                <strong>{t.name}</strong>
              </Link>{" "}
              ({t.slug}) &mdash; {t.status}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
