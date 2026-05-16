/**
 * Agora TypeScript SDK
 *
 * Target API (Spec §8.2):
 *
 *   import { AgoraClient } from "@agora/sdk";
 *   const client = new AgoraClient({ did, privateKey });
 *   const results = await client.search({ capability: "LegalTranslation" });
 *   const job = await client.createJob({ provider: results[0].did, task, budget });
 *
 * NOTE: This is a stub. Signing, webhook verification, and retry handling are TBD.
 */

import ky from "ky";

export interface AgoraClientOptions {
  did: string;
  privateKey: Uint8Array | string;
  baseUrl?: string;
  timeout?: number;
}

export interface AgentMatch {
  did: string;
  name: string;
  score: number;
  pricing: Record<string, unknown>;
}

export interface SearchOptions {
  capability?: string;
  maxPrice?: number;
  minReputation?: number;
  region?: string;
}

export interface CreateJobOptions {
  provider: string;
  task: Record<string, unknown>;
  budget: number;
}

export class AgoraClient {
  private readonly api: typeof ky;
  public readonly did: string;

  constructor(opts: AgoraClientOptions) {
    this.did = opts.did;
    this.api = ky.create({
      prefixUrl: opts.baseUrl ?? "http://localhost:8000",
      timeout: opts.timeout ?? 30_000,
    });
  }

  async search(opts: SearchOptions = {}): Promise<AgentMatch[]> {
    const searchParams = new URLSearchParams();
    if (opts.capability) searchParams.set("capability", opts.capability);
    if (opts.maxPrice !== undefined) searchParams.set("max_price", String(opts.maxPrice));
    if (opts.minReputation !== undefined) searchParams.set("min_reputation", String(opts.minReputation));
    if (opts.region) searchParams.set("region", opts.region);

    const data = await this.api
      .get("v1/search", { searchParams })
      .json<{ matches: AgentMatch[] }>();
    return data.matches ?? [];
  }

  async createJob(opts: CreateJobOptions): Promise<Record<string, unknown>> {
    return await this.api
      .post("v1/jobs", {
        json: {
          provider_did: opts.provider,
          task: opts.task,
          budget: opts.budget,
        },
      })
      .json<Record<string, unknown>>();
  }
}

export const VERSION = "0.1.0";
