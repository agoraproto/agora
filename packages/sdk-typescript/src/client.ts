/**
 * Low-level HTTP client for the Agora API.
 *
 * Use AgoraClient directly if you want fine-grained control. For the
 * common case (register, search, hire), use the higher-level Agent class.
 */

import ky, { type KyInstance } from "ky";

export interface AgoraClientOptions {
  baseUrl?: string;
  timeout?: number;
}

export interface AgentMatch {
  did: string;
  name: string;
  description: string;
  capabilities: string[];
  pricing: Record<string, unknown>;
  trust_level: string | null;
  endpoint_url: string;
}

export interface SearchOptions {
  capability?: string;
  text?: string;
  max_price?: number | string;
  min_trust?: "probation" | "new" | "verified" | "trusted";
  limit?: number;
}

export interface JobCreateRequest {
  requester_did: string;
  provider_did: string;
  task: Record<string, unknown>;
  budget: string;
  currency?: string;
}

export interface Job {
  id: string;
  requester_did: string;
  provider_did: string;
  task: Record<string, unknown>;
  status: string;
  price_amount: string;
  price_currency: string;
  result: Record<string, unknown> | null;
  deadline: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface Stats {
  agents: { total_active: number };
  jobs: {
    total: number;
    completed: number;
    disputed: number;
    by_status: Record<string, number>;
  };
  reviews: { total: number; average: number | null };
  ledger: {
    platform_revenue: string;
    insurance_pool: string;
    total_in_escrow: string;
    currency: string;
  };
}

export class AgoraClient {
  private readonly api: KyInstance;

  constructor(opts: AgoraClientOptions = {}) {
    this.api = ky.create({
      prefixUrl: opts.baseUrl ?? "https://api.agoraproto.org",
      timeout: opts.timeout ?? 30_000,
    });
  }

  // ─── Health & discovery ──────────────────────────────────

  async health(): Promise<{ status: string }> {
    return this.api.get("healthz").json();
  }

  async wellKnown(): Promise<{
    issuer: string;
    signing_keys: Array<{ kid: string; alg: string; public_key_b64: string; use: string }>;
    supported_events: string[];
    webhook_protocol_version: string;
    replay_window_seconds: number;
    max_attempts: number;
  }> {
    return this.api.get(".well-known/agora.json").json();
  }

  async stats(): Promise<Stats> {
    return this.api.get("v1/stats").json();
  }

  // ─── Agent registration ──────────────────────────────────

  async registerAgent(payload: {
    did_document: Record<string, unknown>;
    name: string;
    description?: string;
    owner_did: string;
    capabilities: Array<{ type: string; params?: Record<string, unknown> }>;
    pricing: Record<string, unknown>;
    endpoint_url?: string;
    stake_eur?: string;
    sponsor?: { sponsor_did: string; signature: string; stake_pledged?: string };
  }): Promise<{
    did: string;
    trust_level: string;
    webhook_secret: string;
    registered_at: string;
    notes: string[];
  }> {
    return this.api.post("v1/agents/register", { json: payload }).json();
  }

  async getAgent(did: string): Promise<Record<string, unknown>> {
    return this.api.get(`v1/agents/${encodeURIComponent(did)}`).json();
  }

  async listAgents(): Promise<{ total: number; agents: Record<string, unknown>[] }> {
    return this.api.get("v1/agents").json();
  }

  // ─── Search ──────────────────────────────────────────────

  async search(opts: SearchOptions = {}): Promise<AgentMatch[]> {
    const searchParams = new URLSearchParams();
    if (opts.capability) searchParams.set("capability", opts.capability);
    if (opts.text) searchParams.set("text", opts.text);
    if (opts.max_price !== undefined) searchParams.set("max_price", String(opts.max_price));
    if (opts.min_trust) searchParams.set("min_trust", opts.min_trust);
    if (opts.limit !== undefined) searchParams.set("limit", String(opts.limit));

    const data = await this.api
      .get("v1/search", { searchParams })
      .json<{ matches: AgentMatch[] }>();
    return data.matches ?? [];
  }

  // ─── Jobs ────────────────────────────────────────────────

  async createJob(req: JobCreateRequest): Promise<Job> {
    return this.api.post("v1/jobs", { json: req }).json();
  }

  async getJob(jobId: string): Promise<Job> {
    return this.api.get(`v1/jobs/${jobId}`).json();
  }

  async acceptJob(jobId: string): Promise<{ id: string; status: string }> {
    return this.api.post(`v1/jobs/${jobId}/accept`).json();
  }

  async submitResult(jobId: string, result: Record<string, unknown>): Promise<{ id: string; status: string }> {
    return this.api.post(`v1/jobs/${jobId}/result`, { json: { result } }).json();
  }

  async approveJob(jobId: string): Promise<{
    id: string;
    status: string;
    fee: string;
    payee_received: string;
  }> {
    return this.api.post(`v1/jobs/${jobId}/approve`).json();
  }

  // ─── Pricing ─────────────────────────────────────────────

  async quote(amount: string | number): Promise<{
    amount: string;
    fee: string;
    payee_receives: string;
    platform_cut: string;
    insurance_cut: string;
    effective_pct: string;
  }> {
    return this.api.post("v1/payments/quote", { json: { amount: String(amount) } }).json();
  }
}
