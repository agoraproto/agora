"use client";

import { useEffect, useState } from "react";
import { usePrivy, useWallets } from "@privy-io/react-auth";
import { createPublicClient, http, formatUnits } from "viem";
import { baseSepolia } from "viem/chains";

const USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e" as const;
const FAUCET_URL = "https://faucet.circle.com/"; // Circle's USDC faucet supports Base Sepolia

const ERC20_ABI = [
  {
    type: "function",
    name: "balanceOf",
    stateMutability: "view",
    inputs: [{ name: "owner", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
  },
] as const;

export function WalletPanel() {
  const { authenticated, ready } = usePrivy();
  const { wallets } = useWallets();
  const [usdcBalance, setUsdcBalance] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wallet = wallets[0];
  const address = wallet?.address as `0x${string}` | undefined;

  useEffect(() => {
    if (!address) return;
    const client = createPublicClient({ chain: baseSepolia, transport: http() });
    client
      .readContract({
        address: USDC_BASE_SEPOLIA,
        abi: ERC20_ABI,
        functionName: "balanceOf",
        args: [address],
      })
      .then((raw) => setUsdcBalance(formatUnits(raw as bigint, 6)))
      .catch((e: unknown) => setError(String(e)));
  }, [address]);

  if (!ready || !authenticated) return null;

  return (
    <section style={panel}>
      <h2 style={{ fontSize: "1.1rem", color: "#bbb", margin: 0 }}>Your wallet</h2>
      {!address ? (
        <p style={muted}>Privy is spawning an embedded wallet…</p>
      ) : (
        <>
          <div style={row}>
            <span style={muted}>Address (Base Sepolia)</span>
            <code style={code}>{address}</code>
          </div>
          <div style={row}>
            <span style={muted}>USDC balance</span>
            <span style={value}>
              {error ? "—" : usdcBalance === null ? "loading…" : `${usdcBalance} USDC`}
            </span>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
            <button onClick={() => navigator.clipboard.writeText(address)} style={smBtn}>
              Copy address
            </button>
            <a href={FAUCET_URL} target="_blank" rel="noreferrer" style={{ ...smBtn, textDecoration: "none" }}>
              Get test USDC ↗
            </a>
            <a
              href={`https://sepolia.basescan.org/address/${address}`}
              target="_blank"
              rel="noreferrer"
              style={{ ...smBtn, textDecoration: "none" }}
            >
              View on BaseScan ↗
            </a>
          </div>
          <p style={{ ...muted, marginTop: "0.75rem", fontSize: "0.8rem" }}>
            Test phase. Real USDC on Base Mainnet will go live after the Sepolia run is clean.
          </p>
        </>
      )}
    </section>
  );
}

const panel: React.CSSProperties = {
  background: "#141414",
  border: "1px solid #222",
  borderRadius: 8,
  padding: "1.25rem",
  marginBottom: "2rem",
  display: "flex",
  flexDirection: "column",
  gap: "0.5rem",
};
const row: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center" };
const muted: React.CSSProperties = { color: "#888", fontSize: "0.85rem" };
const code: React.CSSProperties = { fontFamily: "monospace", fontSize: "0.85rem", color: "#7dd3fc" };
const value: React.CSSProperties = { fontFamily: "monospace", fontSize: "1rem", color: "#a7f3d0" };
const smBtn: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #333",
  color: "#bbb",
  padding: "0.35rem 0.7rem",
  borderRadius: 5,
  cursor: "pointer",
  fontSize: "0.8rem",
};
