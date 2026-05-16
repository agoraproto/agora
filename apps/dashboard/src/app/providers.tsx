"use client";

import { PrivyProvider } from "@privy-io/react-auth";
import type { ReactNode } from "react";

const PRIVY_APP_ID = process.env.NEXT_PUBLIC_PRIVY_APP_ID ?? "";

export function Providers({ children }: { children: ReactNode }) {
  if (!PRIVY_APP_ID) {
    return (
      <div style={{ padding: "2rem", color: "#f87171", fontFamily: "system-ui" }}>
        Missing <code>NEXT_PUBLIC_PRIVY_APP_ID</code> in <code>apps/dashboard/.env.local</code>.
        Set it and restart <code>pnpm dev</code>.
      </div>
    );
  }

  return (
    <PrivyProvider
      appId={PRIVY_APP_ID}
      config={{
        loginMethods: ["email", "google", "wallet"],
        appearance: {
          theme: "dark",
          accentColor: "#7dd3fc",
          showWalletLoginFirst: false,
        },
        embeddedWallets: {
          createOnLogin: "users-without-wallets",
        },
        defaultChain: {
          id: 84532,
          name: "Base Sepolia",
          network: "base-sepolia",
          nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
          rpcUrls: { default: { http: ["https://sepolia.base.org"] } },
          blockExplorers: { default: { name: "BaseScan", url: "https://sepolia.basescan.org" } },
        } as never,
      }}
    >
      {children}
    </PrivyProvider>
  );
}
