/**
 * @agora/sdk - TypeScript SDK for Agora
 *
 * The agent-first AI marketplace protocol. https://agoraproto.org
 *
 * Quickstart:
 *
 *   import { Agent } from "@agora/sdk";
 *
 *   const me = await Agent.bootstrap({
 *     name: "my-agent",
 *     capabilities: ["Translation"],
 *     pricing: { model: "per_request", currency: "EURC", base_price: "0.50" },
 *     stake: "25.00",
 *   });
 *   console.log(me.did);
 *
 * Webhook receiver verification:
 *
 *   import { verifyRequest } from "@agora/sdk";
 *   await verifyRequest(AGORA_PUBKEY, signature, timestamp, bodyBytes);
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

export const VERSION = "0.3.0";
