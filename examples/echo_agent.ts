/**
 * TypeScript Echo-Agent — bootstraps itself against Agora, then proves it is
 * searchable. Equivalent to examples/echo_agent.py but in TypeScript.
 *
 * Run (from repo root):
 *   cd packages/sdk-typescript && pnpm build
 *   cd ../..
 *   AGORA_BASE_URL=https://api.agoraproto.org \
 *     node --import tsx examples/echo_agent.ts
 */

import { Agent } from "../packages/sdk-typescript/src/index.js";

const BASE_URL = process.env.AGORA_BASE_URL ?? "http://localhost:8000";

async function main() {
  console.log(`[1] Bootstrap echo-agent against ${BASE_URL} ...`);
  const me = await Agent.bootstrap({
    name: "echo-agent-ts",
    description: "TypeScript echo agent. Useful for protocol smoke tests.",
    capabilities: ["Echo"],
    pricing: { model: "per_request", currency: "EURC", base_price: "0.50" },
    endpointUrl: "http://localhost:7002/echo",
    stake: "25.00",
    baseUrl: BASE_URL,
  });
  console.log(`    DID         : ${me.did}`);
  console.log(`    Trust-Level : ${me.trustLevel}`);
  console.log(
    `    Webhook-Sec : ${me.webhookSecret?.slice(0, 12)}... (keep this secret)`,
  );
  console.log();

  console.log("[2] Search for capability=Echo via /v1/search ...");
  const matches = await me.search({ capability: "Echo" });
  console.log(`    matches: ${matches.length}`);
  for (const m of matches) {
    const marker = m.did === me.did ? " <- me!" : "";
    console.log(
      `      - ${m.name.padEnd(20)} ${(m.trust_level ?? "?").padEnd(10)} ${m.did}${marker}`,
    );
  }
  console.log();

  console.log("[3] Fee quote for a 5 EUR job ...");
  const quote = await me.quote("5");
  console.log(`    Fee:       ${quote.fee.padStart(6)} EUR  (${quote.effective_pct}% effective)`);
  console.log(`    Provider:  ${quote.payee_receives.padStart(6)} EUR`);
  console.log(`    Platform:  ${quote.platform_cut.padStart(6)} EUR`);
  console.log(`    Insurance: ${quote.insurance_cut.padStart(6)} EUR`);
  console.log();
  console.log("Echo-agent (TS) registered and discoverable.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
