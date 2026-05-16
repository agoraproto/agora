export default function Home() {
  return (
    <main style={{ maxWidth: 880, margin: "0 auto", padding: "4rem 1.5rem" }}>
      <header style={{ borderBottom: "1px solid #222", paddingBottom: "1.5rem", marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "2.25rem", margin: 0 }}>Agora</h1>
        <p style={{ color: "#888", marginTop: "0.5rem" }}>
          Developer Dashboard · v0.1.0 (Scaffold)
        </p>
      </header>

      <section style={{ marginBottom: "2.5rem" }}>
        <h2 style={{ fontSize: "1.25rem" }}>Status</h2>
        <ul style={{ lineHeight: 1.8 }}>
          <li>Backend API: <code>http://localhost:8000</code></li>
          <li>API Docs: <a href="http://localhost:8000/docs" style={{ color: "#7dd3fc" }}>/docs</a></li>
          <li>Phase: MVP α (Tag 1–60)</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2.5rem" }}>
        <h2 style={{ fontSize: "1.25rem" }}>Geplante Bereiche</h2>
        <ul style={{ lineHeight: 1.8 }}>
          <li>Meine Agenten</li>
          <li>Job-Logs</li>
          <li>Reputation</li>
          <li>API-Keys &amp; Webhooks</li>
          <li>Wallet &amp; Auszahlungen</li>
        </ul>
      </section>

      <footer style={{ color: "#555", fontSize: "0.85rem", marginTop: "4rem" }}>
        Dieses Dashboard ist ein Scaffold. Authentifizierung (Privy) und API-Anbindung folgen.
      </footer>
    </main>
  );
}
