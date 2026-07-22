import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: "2rem" }}>
      <h1>RegX</h1>
      <p>Regulatory workflow management platform.</p>
      <nav>
        <Link href="/signin">Sign in</Link>
      </nav>
    </main>
  );
}
