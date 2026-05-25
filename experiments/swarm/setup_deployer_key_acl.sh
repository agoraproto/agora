#!/bin/bash
# Sprint 19c — give the API service read-access to .deployer-key.
#
# The .deployer-key file is mode 600 (owner-only) for good reason — we
# don't want it world-readable. But the API service ('agora-api.service')
# typically runs as a non-root user and therefore cannot read it.
# Result: POST /v1/agents/bootstrap with fund_eth=true returns
# funded_eth_amount=0 and the auto-fund silently fails.
#
# This script:
#   1. Identifies the user the agora-api service runs as
#   2. Grants that user a POSIX ACL read-bit on .deployer-key
#   3. Restarts the API service
#   4. Probes /v1/agents/bootstrap/diagnose to confirm
#
# Idempotent: re-running just refreshes the ACL.

set -e

KEYFILE="/opt/agora/experiments/swarm/.deployer-key"

if [ ! -f "$KEYFILE" ]; then
    echo "❌ $KEYFILE missing — bootstrap auto-fund cannot work without it."
    exit 1
fi

# ── Identify the API service user ───────────────────────────────────
API_USER=$(systemctl show agora-api --property=User --value)
if [ -z "$API_USER" ] || [ "$API_USER" = "" ]; then
    # Empty User= means systemd defaults to root. That's a config error
    # but it would also mean the service can read mode-600 root-owned
    # files just fine, so there's nothing to fix.
    echo "ℹ agora-api.service has no User= directive (runs as root) — no ACL change needed."
    API_USER="root"
fi
echo "=== agora-api.service runs as: $API_USER ==="

# ── Show current state ─────────────────────────────────────────────
echo
echo "=== Before ==="
stat -c "  %a  %U:%G  %n" "$KEYFILE" || true
if command -v getfacl >/dev/null 2>&1; then
    getfacl --omit-header "$KEYFILE" 2>/dev/null | sed 's/^/  /'
fi

# ── Install setfacl if needed ──────────────────────────────────────
if ! command -v setfacl >/dev/null 2>&1; then
    echo
    echo "=== Installing acl package ==="
    apt-get install -y acl >/dev/null
fi

# ── Apply the ACL ──────────────────────────────────────────────────
if [ "$API_USER" != "root" ]; then
    echo
    echo "=== Granting read ACL to $API_USER ==="
    setfacl -m "u:${API_USER}:r" "$KEYFILE"
    # Also drop the regular world-readable bit just in case it had been set
    chmod 600 "$KEYFILE"
fi

# ── Show new state ─────────────────────────────────────────────────
echo
echo "=== After ==="
stat -c "  %a  %U:%G  %n" "$KEYFILE"
if command -v getfacl >/dev/null 2>&1; then
    getfacl --omit-header "$KEYFILE" 2>/dev/null | sed 's/^/  /'
fi

# ── Restart API and probe diagnose endpoint ────────────────────────
echo
echo "=== Restarting agora-api.service ==="
systemctl restart agora-api
sleep 4

echo
echo "=== Probing /v1/agents/bootstrap/diagnose ==="
curl -fsS "http://127.0.0.1:8000/v1/agents/bootstrap/diagnose" \
  | python3 -m json.tool || curl -fsS "https://api.agoraproto.org/v1/agents/bootstrap/diagnose" | python3 -m json.tool

echo
echo "✅ Done. If 'key_readable: true' and 'ready_to_fund: true', the next"
echo "   POST /v1/agents/bootstrap with fund_eth=true should actually fund."
