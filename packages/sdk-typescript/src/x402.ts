/**
 * x402 helper for TypeScript / Node agents.
 *
 * Lets an agent hire a provider on Agora with a single call. Uses viem
 * under the hood for the on-chain bits.
 *
 *   import { hireWithX402 } from "@agora/sdk";
 *   const job = await hireWithX402({
 *     baseUrl: "https://api.agoraproto.org",
 *     requesterDid: me.did,
 *     providerDid: "did:agora:abc...",
 *     task: { prompt: "translate" },
 *     budgetUsdc: "2.50",
 *     rpcUrl: "https://sepolia.base.org",
 *     privateKey: "0x...",
 *     chain: "baseSepolia",
 *   });
 */

import ky from "ky";

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
  {
    type: "function",
    name: "allowance",
    stateMutability: "view",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ name: "", type: "uint256" }],
  },
] as const;

export interface PaymentRequired {
  version: string;
  chain: string;
  chain_id: number;
  asset: { kind: string; address: `0x${string}`; symbol: string; decimals: number };
  amount: string;
  fee_estimate: string;
  recipient_contract: `0x${string}`;
  function: string;
  args: {
    payee: `0x${string}`;
    amount: string;
    taskHash: `0x${string}`;
    deadline: number;
  };
  retry_header: string;
  expires_in_seconds: number;
}

export interface QuoteArgs {
  baseUrl: string;
  providerDid: string;
  task: Record<string, unknown>;
  budgetUsdc: string;
}

export async function quote(args: QuoteArgs): Promise<Record<string, unknown>> {
  return await ky
    .post(`${args.baseUrl.replace(/\/$/, "")}/v1/x402/quote`, {
      json: {
        provider_did: args.providerDid,
        task: args.task,
        budget_usdc: args.budgetUsdc,
      },
      timeout: 10_000,
    })
    .json();
}

export interface HireWithX402Args {
  baseUrl: string;
  requesterDid: string;
  providerDid: string;
  task: Record<string, unknown>;
  budgetUsdc: string;
  rpcUrl: string;
  privateKey: `0x${string}`;
  /** Chain object compatible with viem (e.g. baseSepolia). Required. */
  chain: unknown;
  /** Deadline offset in seconds. Default 24h. */
  deadlineSeconds?: number;
  timeoutMs?: number;
}

/**
 * End-to-end x402 hire: server-quote, on-chain approve+createJob, server-confirm.
 *
 * Returns the final job representation from the server on success.
 * Requires `viem` to be installed in the consuming project.
 */
export async function hireWithX402(
  args: HireWithX402Args,
): Promise<Record<string, unknown>> {
  // Dynamic imports so the SDK doesn't hard-require viem for agents
  // that never use the on-chain helper.
  const { createPublicClient, createWalletClient, http, privateKeyToAccount } =
    await loadViem();

  const base = args.baseUrl.replace(/\/$/, "");
  const deadline = Math.floor(Date.now() / 1000) + (args.deadlineSeconds ?? 24 * 3600);
  const body = {
    requester_did: args.requesterDid,
    provider_did: args.providerDid,
    task: args.task,
    budget_usdc: args.budgetUsdc,
    deadline_unix: deadline,
  };

  // Step 1: expect 402.
  const initial = await fetch(`${base}/v1/x402/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (initial.status !== 402) {
    throw new Error(`expected 402, got ${initial.status}: ${await initial.text()}`);
  }
  const required = JSON.parse(initial.headers.get("X-Payment-Required") ?? "{}") as PaymentRequired;

  // Step 2: on-chain approve + createJob.
  const account = privateKeyToAccount(args.privateKey);
  const wallet = createWalletClient({ account, chain: args.chain as any, transport: http(args.rpcUrl) });
  const pub = createPublicClient({ chain: args.chain as any, transport: http(args.rpcUrl) });
  const amount = BigInt(required.amount);

  const allowance = (await pub.readContract({
    address: required.asset.address,
    abi: ERC20_ABI,
    functionName: "allowance",
    args: [account.address, required.recipient_contract],
  })) as bigint;
  if (allowance < amount) {
    const txApprove = await wallet.writeContract({
      address: required.asset.address,
      abi: ERC20_ABI,
      functionName: "approve",
      args: [required.recipient_contract, amount],
    });
    await pub.waitForTransactionReceipt({ hash: txApprove });
  }

  const txCreate = await wallet.writeContract({
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
  await pub.waitForTransactionReceipt({ hash: txCreate });

  // Step 3: retry with X-Payment-Tx.
  const confirmed = await fetch(`${base}/v1/x402/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Payment-Tx": txCreate },
    body: JSON.stringify(body),
  });
  if (!confirmed.ok) {
    throw new Error(`server rejected: ${confirmed.status} ${await confirmed.text()}`);
  }
  return await confirmed.json();
}

async function loadViem(): Promise<{
  createPublicClient: any;
  createWalletClient: any;
  http: any;
  privateKeyToAccount: any;
}> {
  try {
    const viem = await import("viem");
    const accounts = await import("viem/accounts");
    return {
      createPublicClient: (viem as any).createPublicClient,
      createWalletClient: (viem as any).createWalletClient,
      http: (viem as any).http,
      privateKeyToAccount: (accounts as any).privateKeyToAccount,
    };
  } catch (e) {
    throw new Error(
      "x402 helper requires `viem`. Install with: npm install viem",
    );
  }
}
