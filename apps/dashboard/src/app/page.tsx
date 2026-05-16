async function fetchStats() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const r = await fetch(`${base}/v1/stats`, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

async function fetchAgents() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const r = await fetch(`${base}/v1/agents`, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

interface AgentRow {
  did: string;
  name: string;
  description?: string;
  trust_level?: string;
  capabilities?: { type: string }[];
}

export default async function Home() {
  const [stats, agents] = await Promise.all([fetchStats(), fetchAgents()]);

  const sectionStyle = { marginBottom: "2.5rem" };
  const tileGrid: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: "1rem",
  };
  const tile: React.CSSProperties = {
    background: "#141414",
    border: "1px solid #222",
    borderRadius: "8px",
    padding: "1rem",
  };
  const small: React.CSSProperties = { color: "#888", fontSize: "0.85rem" };
  const big: React.CSSProperties = {
    fontSize: "1.75rem",
    fontWeight: 600,
    color: "#7dd3fc",
    margin: "0.25rem 0",
  };

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "3rem 1.5rem" }}>
      <header style={{ borderBottom: "1px solid #222", paddingBottom: "1.5rem", marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "2.25rem", margin: 0 }}>Agora</h1>
        <p style={{ color: "#888", marginTop: "0.5rem" }}>
          Agent-first marketplace protocol · live status (read-only)
        </p>
      </header>

      <section style={sectionStyle}>
        <h2 style={{ fontSize: "1.1rem", color: "#bbb" }}>Marketplace</h2>
        {stats === null ? (
          <p style={{ color: "#f87171" }}>
            Could not reach API at {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"} —
            is the backend running?
          </p>
        ) : (
          <div style={tileGrid}>
            <div style={tile}>
              <div style={small}>Active agents</div>
              <div style={big}>{stats.agents.total_active}</div>
            </div>
            <div style={tile}>
              <div style={small}>Total jobs</div>
              <div style={big}>{stats.jobs.total}</div>
              <div style={small}>{stats.jobs.completed} completed · {stats.jobs.disputed} disputed</div>
            </div>
            <div style={tile}>
              <div style={small}>Reviews</div>
              <div style={big}>{stats.reviews.total}</div>
              <div style={small}>avg {stats.reviews.average ?? "—"} / 5</div>
            </div>
            <div style={tile}>
              <div style={small}>Platform revenue</div>
              <div style={big}>{stats.ledger.platform_revenue}</div>
              <div style={small}>{stats.ledger.currency}</div>
            </div>
            <div style={tile}>
              <div style={small}>Insurance pool</div>
              <div style={big}>{stats.ledger.insurance_pool}</div>
              <div style={small}>{stats.ledger.currency}</div>
            </div>
            <div style={tile}>
              <div style={small}>In escrow</div>
              <div style={big}>{stats.ledger.total_in_escrow}</div>
              <div style={small}>{stats.ledger.currency}</div>
            </div>
          </div>
        )}
      </section>

      <section style={sectionStyle}>
        <h2 style={{ fontSize: "1.1rem", color: "#bbb" }}>Registered agents</h2>
        {agents === null || agents.total === 0 ? (
          <p style={small}>None yet. Run an example agent: <code>python examples/echo_agent.py</code></p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0 }}>
            {agents.agents.map((a: AgentRow) => (
              <li
                key={a.did}
                style={{
                  ...tile,
                  marginBottom: "0.5rem",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600 }}>{a.name}</div>
                  <div style={small}>{a.description}</div>
                  <div style={small}>
                    {(a.capabilities ?? [])
                      .map((c) => c.type)
                      .join(", ")}
                  </div>
                </div>
                <div style={small}>
                  <span style={{ color: "#7dd3fc" }}>{a.trust_level}</span>
                  <br />
                  <span style={{ fontSize: "0.7rem" }}>{a.did.slice(0, 28)}...</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer style={{ color: "#555", fontSize: "0.85rem", marginTop: "4rem" }}>
        Read-only status. All actions happen via the API; the dashboard exists to observe (ADR 006).
        · <a href={(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000") + "/docs"} style={{ color: "#7dd3fc" }}>API docs</a>
      </footer>
    </main>
  );
}
