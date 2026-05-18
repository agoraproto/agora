"use client";

import { useState } from "react";
import { usePrivy, useWallets } from "@privy-io/react-auth";
import {
  createPublicClient,
  createWalletClient,
  custom,
  encodeFunctionData,
  http,
  keccak256,
  parseUnits,
  stringToBytes,
  toBytes,
  toHex,
} from "viem";
import { baseSepolia } from "viem/chains";

const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e" as const;
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ERC20_ABI = [
  {
    type: "function",
    name: "approve",
    stateMutability: "nonpayable",
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
] as const;

const ESCROW_ABI = [
  {
    type: "function",
    name: "createJob",
    stateMutability: "nonpayable",
    inputs: [
      { name: "payee", type: "address" },
      { name: "amount", type: "uint256" },
      { name: "taskHash", type: "bytes32" },
      { name: "deadline", type: "uint64" },
    ],
    outputs: [{ name: "jobId", type: "uint256" }],
  },
] as const;

interface PaymentRequired {
  recipient_contract: `0x${string}`;
  args: {
    payee: `0x${string}`;
    amount: string;
    taskHash: `0x${string}`;
    deadline: number;
  };
}

export function HirePanel() {
  const { authenticated, ready } = usePrivy();
  const { wallets } = useWallets();
  const [requesterDid, setRequesterDid] = useState("");
  const [providerDid, setProviderDid] = useState("");
  const [task, setTask] = useState('{"prompt":"echo hello"}');
  const [budget, setBudget] = useState("1.00");
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const wallet = wallets[0];

  function append(line: string) {
    setLog((prev) => [...prev, line]);
  }

  async function hire() {
    if (!wallet) return;
    setBusy(true);
    setLog([]);
    try {
      const provider = await wallet.getEthereumProvider();
      const walletClient = createWalletClient({
        account: wallet.address as `0x${string}`,
        chain: baseSepolia,
        transport: custom(provider),
      });
      const publicClient = createPublicClient({ chain: baseSepolia, transport: http() });

      // Step 1 — call our API without payment, expect 402
      const taskObj = JSON.parse(task);
      append("→ POST /v1/x402/jobs (no payment)");
      const res1 = await fetch(`${API}/v1/x402/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester_did: requesterDid,
          provider_did: providerDid,
          task: taskObj,
          budget_usdc: budget,
          deadline_unix: Math.floor(Date.now() / 1000) + 24 * 3600,
        }),
      });
      if (res1.status !== 402) {
        throw new Error(`expected 402, got ${res1.status}: ${await res1.text()}`);
      }
      const required = JSON.parse(res1.headers.get("X-Payment-Required") ?? "{}") as PaymentRequired;
      append(`← 402 Payment Required, contract ${required.recipient_contract}`);

      // Step 2 — approve USDC to AgoraEscrow
      const amount = BigInt(required.args.amount);
      append(`→ USDC.approve(${required.recipient_contract}, ${amount})`);
      const approveTx = await walletClient.writeContract({
        address: USDC,
        abi: ERC20_ABI,
        functionName: "approve",
        args: [required.recipient_contract, amount],
      });
      append(`  tx ${approveTx} (waiting…)`);
      await publicClient.waitForTransactionReceipt({ hash: approveTx });

      // Step 3 — call AgoraEscrow.createJob
      append(`→ AgoraEscrow.createJob(${required.args.payee}, ${amount}, …)`);
      const createTx = await walletClient.writeContract({
        address: required.recipient_contract,
        abi: ESCROW_ABI,
        functionName: "createJob",
        args: [
          required.args.payee,
          amount,
          required.args.taskHash,
          BigInt(required.args.deadline),
        ],
      });
      append(`  tx ${createTx} (waiting for confirmation…)`);
      await publicClient.waitForTransactionReceipt({ hash: createTx });

      // Step 4 — retry our POST with X-Payment-Tx
      append("→ POST /v1/x402/jobs with X-Payment-Tx");
      const res2 = await fetch(`${API}/v1/x402/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Payment-Tx": createTx,
        },
        body: JSON.stringify({
          requester_did: requesterDid,
          provider_did: providerDid,
          task: taskObj,
          budget_usdc: budget,
          deadline_unix: required.args.deadline,
        }),
      });
      if (!res2.ok) {
        throw new Error(`API rejected: ${res2.status} ${await res2.text()}`);
      }
      const job = await res2.json();
      append(`✓ Job created — id ${job.id}, on-chain jobId ${job.onchain_job_id}`);
    } catch (e) {
      append(`✗ ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !authenticated) return null;

  return (
    <section style={panel}>
      <h2 style={{ fontSize: "1.1rem", color: "#bbb", margin: 0 }}>Hire an agent (x402)</h2>
      <input style={input} placeholder="requester DID (you)" value={requesterDid} onChange={(e) => setRequesterDid(e.target.value)} />
      <input style={input} placeholder="provider DID" value={providerDid} onChange={(e) => setProviderDid(e.target.value)} />
      <textarea style={{ ...input, fontFamily: "monospace", minHeight: 64 }} value={task} onChange={(e) => setTask(e.target.value)} />
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <span style={muted}>Budget (USDC)</span>
        <input style={{ ...input, width: 80 }} value={budget} onChange={(e) => setBudget(e.target.value)} />
        <button onClick={hire} disabled={busy} style={primaryBtn}>
          {busy ? "Hiring…" : "Hire"}
        </button>
      </div>
      {log.length > 0 && (
        <pre style={logBox}>{log.join("\n")}</pre>
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
const input: React.CSSProperties = {
  background: "#0a0a0a",
  border: "1px solid #333",
  borderRadius: 5,
  padding: "0.4rem 0.6rem",
  color: "#eee",
  fontSize: "0.85rem",
};
const muted: React.CSSProperties = { color: "#888", fontSize: "0.85rem" };
const primaryBtn: React.CSSProperties = {
  background: "#7dd3fc",
  border: "none",
  color: "#0a0a0a",
  padding: "0.4rem 1rem",
  borderRadius: 5,
  cursor: "pointer",
  fontWeight: 600,
};
const logBox: React.CSSProperties = {
  background: "#0a0a0a",
  border: "1px solid #222",
  borderRadius: 5,
  padding: "0.75rem",
  fontSize: "0.75rem",
  color: "#a7f3d0",
  whiteSpace: "pre-wrap",
  marginTop: "0.5rem",
  maxHeight: 240,
  overflow: "auto",
};
