"use client";

import { usePrivy } from "@privy-io/react-auth";

export function LoginButton() {
  const { ready, authenticated, user, login, logout } = usePrivy();

  if (!ready) {
    return (
      <button disabled style={btn(false)} aria-busy>
        Loading…
      </button>
    );
  }

  if (!authenticated) {
    return (
      <button onClick={() => login()} style={btn(true)}>
        Sign in with Privy
      </button>
    );
  }

  const walletShort = user?.wallet?.address
    ? `${user.wallet.address.slice(0, 6)}…`
    : undefined;
  const label =
    user?.email?.address ??
    user?.google?.email ??
    walletShort ??
    "Logged in";

  return (
    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
      <span style={{ color: "#7dd3fc", fontSize: "0.9rem" }}>{label}</span>
      <button onClick={() => logout()} style={btn(false)}>
        Sign out
      </button>
    </div>
  );
}

function btn(primary: boolean): React.CSSProperties {
  return {
    padding: "0.5rem 1rem",
    borderRadius: 6,
    border: primary ? "none" : "1px solid #333",
    background: primary ? "#7dd3fc" : "transparent",
    color: primary ? "#0a0a0a" : "#bbb",
    cursor: "pointer",
    fontWeight: 500,
    fontSize: "0.9rem",
  };
}
