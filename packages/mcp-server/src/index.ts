#!/usr/bin/env node
/**
 * Agora MCP Server.
 *
 * Exposes Agora as a Model Context Protocol tool, so any MCP-aware client
 * (Claude Desktop, Cursor, Cline, Continue, ...) can call into the
 * marketplace directly - find providers, hire, pay, retrieve results -
 * without any client-side glue code.
 *
 * Run via Claude Desktop config:
 *   {
 *     "mcpServers": {
 *       "agora": {
 *         "command": "npx",
 *         "args": ["-y", "@agora/mcp"],
 *         "env": { "AGORA_BASE_URL": "https://api.agoraproto.org" }
 *       }
 *     }
 *   }
 *
 * Or globally: `npm i -g @agora/mcp` then point command to `agora-mcp`.
 *
 * Auth model: the MCP server reads `AGORA_AGENT_SECRET` from env (a base64
 * Ed25519 private key, see @agora/sdk's AgentIdentity.exportSecret). If set,
 * it identifies the calling agent. If not, only read-only tools work
 * (search, get_agent, stats).
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import ky, { type KyInstance } from "ky";

const AGORA_BASE_URL = process.env.AGORA_BASE_URL ?? "https://api.agoraproto.org";
const AGORA_AGENT_DID = process.env.AGORA_AGENT_DID;

const api: KyInstance = ky.create({
  prefixUrl: AGORA_BASE_URL,
  timeout: 30_000,
});

// ─── Tool definitions ──────────────────────────────────

const TOOLS = [
  {
    name: "agora_search",
    description:
      "Search the Agora marketplace for agents that can perform a capability. " +
      "Use this when the user (or the calling LLM) needs a specialized skill: " +
      "translation, fact-checking, code review, image generation, etc. " +
      "Returns up to 50 providers with their DID, name, pricing, and trust level.",
    inputSchema: {
      type: "object",
      properties: {
        capability: {
          type: "string",
          description:
            "What the agent should be able to do, e.g. 'Translation', 'FactCheck', 'CodeReview'.",
        },
        text: {
          type: "string",
          description: "Free-text filter applied to agent name/description.",
        },
        max_price: {
          type: "string",
          description: "Maximum acceptable base_price in EURC (decimal string).",
        },
        min_trust: {
          type: "string",
          enum: ["probation", "new", "verified", "trusted"],
          description: "Only return agents with at least this trust level.",
        },
      },
    },
  },
  {
    name: "agora_quote",
    description:
      "Calculate the fee Agora charges for a transaction of a given amount. " +
      "Fee is 1% of the price, minimum 0.50 EUR, maximum 25 EUR. " +
      "Use this BEFORE creating a job to show the user the true cost.",
    inputSchema: {
      type: "object",
      properties: {
        amount: {
          type: "string",
          description: "The amount to be paid to the provider, in EUR (decimal string).",
        },
      },
      required: ["amount"],
    },
  },
  {
    name: "agora_get_agent",
    description:
      "Fetch full details of a specific Agora agent by DID, including " +
      "capabilities, pricing, reputation, completed jobs.",
    inputSchema: {
      type: "object",
      properties: {
        did: {
          type: "string",
          description: "The agent's DID, e.g. did:agora:xyz...",
        },
      },
      required: ["did"],
    },
  },
  {
    name: "agora_stats",
    description:
      "Get marketplace-wide statistics: total active agents, total jobs, " +
      "completed jobs, platform revenue. Useful to gauge whether Agora is " +
      "the right place to look for a capability.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "agora_get_job",
    description:
      "Look up the current status of a job by job_id (UUID). " +
      "Status values: offered, accepted, in_progress, submitted, completed, " +
      "disputed, cancelled, refunded.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Job UUID returned by agora_hire." },
      },
      required: ["job_id"],
    },
  },
  {
    name: "agora_hire",
    description:
      "Create a job offer to a provider. Locks the budget in escrow. " +
      "REQUIRES the calling agent's DID to be set via AGORA_AGENT_DID env var. " +
      "The provider's webhook will fire; you can then poll agora_get_job until " +
      "status='submitted', then call agora_approve to release payment.",
    inputSchema: {
      type: "object",
      properties: {
        provider_did: { type: "string", description: "The provider's DID." },
        task: {
          type: "object",
          description: "Free-form task description, sent to the provider verbatim.",
        },
        budget: {
          type: "string",
          description: "Amount to pay in EUR (decimal string).",
        },
      },
      required: ["provider_did", "task", "budget"],
    },
  },
  {
    name: "agora_approve",
    description:
      "Approve a submitted job, releasing escrow to the provider. " +
      "Only call this if the result is acceptable. To reject, call agora_dispute instead.",
    inputSchema: {
      type: "object",
      properties: { job_id: { type: "string", description: "Job UUID." } },
      required: ["job_id"],
    },
  },
  {
    name: "agora_well_known",
    description:
      "Fetch Agora's public metadata (signing key, supported webhook events, " +
      "replay window). Use to verify Agora is reachable before any other call.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "agora_x402_quote",
    description:
      "Get a USDC-denominated price quote for hiring a specific provider, " +
      "including platform fee and provider payout. Read-only; does not " +
      "create a job. Use to compare providers before committing.",
    inputSchema: {
      type: "object",
      properties: {
        provider_did: { type: "string" },
        task: { type: "object", description: "Job spec; opaque to Agora." },
        budget_usdc: { type: "string", description: "Decimal USDC, e.g. '2.50'." },
      },
      required: ["provider_did", "task", "budget_usdc"],
    },
  },
  {
    name: "agora_x402_payment_required",
    description:
      "Returns the on-chain payment instructions for hiring a provider. " +
      "Two-phase flow: (1) call this to get contract address, USDC amount, " +
      "taskHash, deadline; (2) you broadcast AgoraEscrow.createJob() on Base; " +
      "(3) call agora_x402_confirm with the tx hash. " +
      "The MCP server never sees the agent's private key.",
    inputSchema: {
      type: "object",
      properties: {
        requester_did: { type: "string" },
        provider_did: { type: "string" },
        task: { type: "object" },
        budget_usdc: { type: "string" },
        deadline_seconds: { type: "integer", description: "Default 86400 (24h)." },
      },
      required: ["requester_did", "provider_did", "task", "budget_usdc"],
    },
  },
  {
    name: "agora_x402_confirm",
    description:
      "Confirm an on-chain payment by submitting the tx hash from " +
      "AgoraEscrow.createJob(). Server verifies the receipt and creates the job.",
    inputSchema: {
      type: "object",
      properties: {
        requester_did: { type: "string" },
        provider_did: { type: "string" },
        task: { type: "object" },
        budget_usdc: { type: "string" },
        deadline_unix: { type: "integer" },
        tx_hash: { type: "string" },
      },
      required: ["requester_did", "provider_did", "task", "budget_usdc", "deadline_unix", "tx_hash"],
    },
  },
  {
    name: "agora_x402_lifecycle",
    description:
      "Drive the post-hire lifecycle of an on-chain x402 job. Same two-phase " +
      "pattern as agora_x402_payment_required + confirm, but for the four " +
      "post-hire actions: 'result' (provider submits), 'approve' (requester " +
      "releases escrow), 'refund' (requester after deadline), 'dispute' " +
      "(either party). If tx_hash is omitted the server replies with the " +
      "X-Payment-Required payload describing the on-chain call to make; " +
      "include tx_hash on the retry to commit the state change in the DB.",
    inputSchema: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["result", "approve", "refund", "dispute"],
          description: "Which lifecycle step to drive.",
        },
        job_id: {
          type: "string",
          description: "DB UUID of the job (the 'id' field from agora_x402_confirm).",
        },
        result: {
          type: "object",
          description: "Required for action='result'. The result payload; gets hashed for the on-chain commitment.",
        },
        reason: {
          type: "string",
          description: "Required for action='dispute'. Short human-readable reason.",
        },
        raised_by_did: {
          type: "string",
          description: "Required for action='dispute'. DID of the party raising the dispute.",
        },
        evidence: {
          type: "object",
          description: "Optional for action='dispute'. Off-chain evidence dict.",
        },
        tx_hash: {
          type: "string",
          description: "Omit on first call (to get 402 instructions). Include on retry (with the AgoraEscrow tx hash) to commit.",
        },
      },
      required: ["action", "job_id"],
    },
  },
] as const;

// ─── Tool implementations ──────────────────────────────

async function callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  switch (name) {
    case "agora_search": {
      const params = new URLSearchParams();
      if (args.capability) params.set("capability", String(args.capability));
      if (args.text) params.set("text", String(args.text));
      if (args.max_price) params.set("max_price", String(args.max_price));
      if (args.min_trust) params.set("min_trust", String(args.min_trust));
      return await api.get("v1/search", { searchParams: params }).json();
    }

    case "agora_quote": {
      return await api
        .post("v1/payments/quote", { json: { amount: String(args.amount) } })
        .json();
    }

    case "agora_get_agent": {
      return await api.get(`v1/agents/${encodeURIComponent(String(args.did))}`).json();
    }

    case "agora_stats": {
      return await api.get("v1/stats").json();
    }

    case "agora_get_job": {
      return await api.get(`v1/jobs/${String(args.job_id)}`).json();
    }

    case "agora_hire": {
      if (!AGORA_AGENT_DID) {
        throw new Error(
          "agora_hire requires AGORA_AGENT_DID env var. " +
            "Register an agent first via @agora/sdk's Agent.bootstrap() and " +
            "set AGORA_AGENT_DID to the resulting DID.",
        );
      }
      return await api
        .post("v1/jobs", {
          json: {
            requester_did: AGORA_AGENT_DID,
            provider_did: args.provider_did,
            task: args.task,
            budget: String(args.budget),
          },
        })
        .json();
    }

    case "agora_approve": {
      return await api.post(`v1/jobs/${String(args.job_id)}/approve`).json();
    }

    case "agora_well_known": {
      return await api.get(".well-known/agora.json").json();
    }

    case "agora_x402_quote": {
      return await api
        .post("v1/x402/quote", {
          json: {
            provider_did: args.provider_did,
            task: args.task,
            budget_usdc: String(args.budget_usdc),
          },
        })
        .json();
    }

    case "agora_x402_payment_required": {
      const deadlineSeconds = Number(args.deadline_seconds ?? 86400);
      const deadlineUnix = Math.floor(Date.now() / 1000) + deadlineSeconds;
      const resp = await fetch(`${AGORA_BASE_URL}/v1/x402/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester_did: args.requester_did,
          provider_did: args.provider_did,
          task: args.task,
          budget_usdc: String(args.budget_usdc),
          deadline_unix: deadlineUnix,
        }),
      });
      if (resp.status !== 402) {
        throw new Error(`expected 402, got ${resp.status}: ${await resp.text()}`);
      }
      const required = resp.headers.get("X-Payment-Required");
      if (!required) throw new Error("X-Payment-Required header missing");
      return { ...JSON.parse(required), deadline_unix: deadlineUnix };
    }

    case "agora_x402_confirm": {
      const resp = await fetch(`${AGORA_BASE_URL}/v1/x402/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Payment-Tx": String(args.tx_hash),
        },
        body: JSON.stringify({
          requester_did: args.requester_did,
          provider_did: args.provider_did,
          task: args.task,
          budget_usdc: String(args.budget_usdc),
          deadline_unix: args.deadline_unix,
        }),
      });
      if (!resp.ok) {
        throw new Error(`server rejected: ${resp.status} ${await resp.text()}`);
      }
      return await resp.json();
    }

    case "agora_x402_lifecycle": {
      const action = String(args.action);
      const jobId = String(args.job_id);
      if (!["result", "approve", "refund", "dispute"].includes(action)) {
        throw new Error(
          `agora_x402_lifecycle: action must be one of result|approve|refund|dispute, got ${action}`,
        );
      }

      // Build the per-action body. The server hashes / verifies this
      // canonically — so it must be identical between the first call
      // (to get the 402) and the retry (with X-Payment-Tx).
      let body: Record<string, unknown> = {};
      if (action === "result") {
        if (args.result === undefined) {
          throw new Error("agora_x402_lifecycle: action='result' requires a `result` object");
        }
        body = { result: args.result };
      } else if (action === "dispute") {
        if (args.reason === undefined || args.raised_by_did === undefined) {
          throw new Error(
            "agora_x402_lifecycle: action='dispute' requires `reason` and `raised_by_did`",
          );
        }
        body = {
          reason: String(args.reason),
          raised_by_did: String(args.raised_by_did),
          evidence: args.evidence ?? {},
        };
      }
      // approve and refund: empty body.

      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (args.tx_hash) headers["X-Payment-Tx"] = String(args.tx_hash);

      const resp = await fetch(`${AGORA_BASE_URL}/v1/x402/jobs/${jobId}/${action}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      // First call: server returns 402 with X-Payment-Required. Surface
      // that to the LLM as a structured object so it can decide what to
      // broadcast next.
      if (resp.status === 402) {
        const required = resp.headers.get("X-Payment-Required");
        if (!required) throw new Error("X-Payment-Required header missing on 402 response");
        return {
          status: "payment_required",
          x_payment_required: JSON.parse(required),
          next: `Broadcast the contract call described above, then call this tool again with tx_hash=<hash>.`,
        };
      }

      if (!resp.ok) {
        throw new Error(`server rejected: ${resp.status} ${await resp.text()}`);
      }
      return await resp.json();
    }

    default:
      throw new Error(`unknown tool: ${name}`);
  }
}

// ─── Server bootstrap ──────────────────────────────────

async function main() {
  const server = new Server(
    { name: "agora-mcp", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS as unknown as Array<{
      name: string;
      description: string;
      inputSchema: object;
    }>,
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
      const result = await callTool(name, (args ?? {}) as Record<string, unknown>);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return {
        content: [{ type: "text", text: `Error: ${msg}` }],
        isError: true,
      };
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);

  // eslint-disable-next-line no-console
  console.error(`[agora-mcp] connected to ${AGORA_BASE_URL}`);
}

main().catch((e) => {
  console.error("[agora-mcp] fatal:", e);
  process.exit(1);
});
