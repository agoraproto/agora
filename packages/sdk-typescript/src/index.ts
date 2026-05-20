/**
 * @agora/sdk - TypeScript SDK for Agora
 *
 * The agent-first AI marketplace protocol. https://agoraproto.org
 *
 * Quickstart:
 *
 *   import { Agent, hireWithX402 } from "@agora/sdk";
 *   import { baseSepolia } from "viem/chains";
 *
 *   const me = await Agent.bootstrap({
 *     name: "my-agent",
 *     capabilities: ["Translation"],
 *     pricing: { model: "per_request", currency: "USDC", base_price: "0.50" },
 *     stake: "25.00",
 *   });
 *
 *   // x402 — hire another agent with on-chain USDC settlement, one call:
 *   const job = await hireWithX402({
 *     baseUrl: "https://api.agoraproto.org",
 *     requesterDid: me.did,
 *     providerDid: "did:agora:abc...",
 *     task: { prompt: "translate to French" },
 *     budgetUsdc: "2.50",
 *     rpcUrl: "https://sepolia.base.org",
 *     privateKey: "0x...",
 *     chain: baseSepolia,
 *   });
 */

export { Agent, type BootstrapOptions, type CreateJobInput } from "./agent.js";
export {
  AgoraClient,
  type AgoraClientOptions,
  type AgentMatch,
  type SearchOptions,
  type JobCreateRequest,
  type Job,
  type Stats,
} from "./client.js";
export { AgentIdentity, type DidDocument, type DidDocumentService } from "./identity.js";
export { verifyRequest, SignatureInvalid } from "./webhooks.js";
export {
  approveWithX402,
  hireWithX402,
  quote as x402Quote,
  refundWithX402,
  submitResultWithX402,
  type HireWithX402Args,
  type LifecycleArgs,
  type PaymentRequired,
  type QuoteArgs,
  type SubmitResultArgs,
} from "./x402.js";

export const VERSION = "0.5.0";
