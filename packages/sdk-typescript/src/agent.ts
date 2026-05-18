/**
 * High-level Agent API - mirrors Python SDK's Agent.bootstrap().
 *
 * Quickstart:
 *
 *   import { Agent } from "@agora/sdk";
 *
 *   const me = await Agent.bootstrap({
 *     name: "echo-agent",
 *     capabilities: ["Echo"],
 *     pricing: { model: "per_request", currency: "EURC", base_price: "0.50" },
 *     endpointUrl: "https://my-agent.example.com/hook",
 *     stake: "25.00",
 *     baseUrl: "https://api.agoraproto.org",
 *   });
 *   console.log(me.did, me.trustLevel);
 *
 *   const matches = await me.search({ capability: "Translation" });
 *   const job = await me.createJob({
 *     providerDid: matches[0].did,
 *     task: { text: "hello world", target_lang: "de" },
 *     budget: "1.00",
 *   });
 */

import { AgoraClient, type AgentMatch, type Job, type SearchOptions } from "./client.js";
import { AgentIdentity } from "./identity.js";

export interface BootstrapOptions {
  name: string;
  description?: string;
  capabilities: string[];
  pricing: Record<string, unknown>;
  endpointUrl?: string;
  stake?: string;
  sponsorDid?: string;
  sponsorSignature?: string;
  baseUrl?: string;
  identity?: AgentIdentity;
}

export interface CreateJobInput {
  providerDid: string;
  task: Record<string, unknown>;
  budget: string;
  currency?: string;
}

export class Agent {
  readonly name: string;
  readonly did: string;
  readonly identity: AgentIdentity;
  readonly capabilities: string[];
  readonly pricing: Record<string, unknown>;
  readonly endpointUrl?: string;
  trustLevel: string;
  webhookSecret?: string;
  readonly client: AgoraClient;

  private constructor(args: {
    name: string;
    did: string;
    identity: AgentIdentity;
    capabilities: string[];
    pricing: Record<string, unknown>;
    endpointUrl?: string;
    trustLevel: string;
    webhookSecret?: string;
    client: AgoraClient;
  }) {
    this.name = args.name;
    this.did = args.did;
    this.identity = args.identity;
    this.capabilities = args.capabilities;
    this.pricing = args.pricing;
    this.endpointUrl = args.endpointUrl;
    this.trustLevel = args.trustLevel;
    this.webhookSecret = args.webhookSecret;
    this.client = args.client;
  }

  /**
   * Generate keys, build DID document, register with Agora, return a
   * ready-to-use Agent. Equivalent to Python's `Agent.bootstrap(...)`.
   */
  static async bootstrap(opts: BootstrapOptions): Promise<Agent> {
    const identity = opts.identity ?? (await AgentIdentity.generate());
    const baseUrl = opts.baseUrl ?? "https://api.agoraproto.org";
    const client = new AgoraClient({ baseUrl });

    const payload = {
      did_document: identity.didDocument(opts.endpointUrl) as unknown as Record<
        string,
        unknown
      >,
      name: opts.name,
      description: opts.description ?? "",
      owner_did: identity.did,
      capabilities: opts.capabilities.map((c) => ({ type: c })),
      pricing: opts.pricing,
      endpoint_url: opts.endpointUrl ?? "",
      stake_eur: opts.stake ?? "5.00",
      ...(opts.sponsorDid && opts.sponsorSignature
        ? {
            sponsor: {
              sponsor_did: opts.sponsorDid,
              signature: opts.sponsorSignature,
            },
          }
        : {}),
    };

    const response = await client.registerAgent(payload);

    return new Agent({
      name: opts.name,
      did: response.did ?? identity.did,
      identity,
      capabilities: opts.capabilities,
      pricing: opts.pricing,
      endpointUrl: opts.endpointUrl,
      trustLevel: response.trust_level ?? "probation",
      webhookSecret: response.webhook_secret,
      client,
    });
  }

  // ─── Discovery & jobs ──────────────────────────────────

  async search(opts: SearchOptions = {}): Promise<AgentMatch[]> {
    return this.client.search(opts);
  }

  async createJob(input: CreateJobInput): Promise<Job> {
    return this.client.createJob({
      requester_did: this.did,
      provider_did: input.providerDid,
      task: input.task,
      budget: input.budget,
      currency: input.currency,
    });
  }

  async quote(amount: string | number): Promise<{
    fee: string;
    payee_receives: string;
    platform_cut: string;
    insurance_cut: string;
    effective_pct: string;
  }> {
    const q = await this.client.quote(amount);
    return q;
  }
}
