"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
          router.push("/signin");
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
      {items.length === 0 ? (
        <p>No organisations found.</p>
      ) : (
        <ul>
          {items.map((t) => (
            <li key={t.id}>
              <strong>{t.name}</strong> ({t.slug}) &mdash; {t.status}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
