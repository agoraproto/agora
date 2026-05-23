#!/bin/bash
# Sprint 14 — set up the auto-topup systemd-timer.
#
# Reads the deployer key from Zugangsdaten.txt's wallet line if available,
# otherwise prompts. Writes the key to /opt/agora/experiments/swarm/.deployer-key
# (gitignored, mode 600). Installs systemd unit + timer and starts both.

set -e

SWARM="/opt/agora/experiments/swarm"
KEYFILE="$SWARM/.deployer-key"

# ── Ensure deployer key is on disk ──
if [ -s "$KEYFILE" ]; then
    echo "Deployer key already at $KEYFILE — keeping it."
else
    # Prompt only on first run. Hidden input, never echoed, never logged.
    # Andreas pastes his deployer key once; on later re-runs we re-use
    # the file. The key file is mode 600 + gitignored.
    echo "First run — need the deployer wallet private key (Sepolia testnet)."
    echo "It is used to send USDC top-ups to swarm buyers."
    echo "The key will be stored in $KEYFILE with mode 600. Never echoed."
    read -r -s -p "Paste private key (hex, with or without 0x prefix): " KEY
    echo
    if [ -z "$KEY" ]; then
        echo "❌ No key entered — aborting."
        exit 1
    fi
    # Sanity-check: must be 64 or 66 hex chars
    KEY_NO_0X="${KEY#0x}"
    if ! [[ "$KEY_NO_0X" =~ ^[0-9a-fA-F]{64}$ ]]; then
        echo "❌ Key doesn't look like a valid hex private key (expected 64 hex chars)."
        exit 1
    fi
    echo "$KEY" > "$KEYFILE"
    chmod 600 "$KEYFILE"
    unset KEY KEY_NO_0X
    echo "Saved key to $KEYFILE (mode 600, owner-only)."
fi

# ── systemd service unit (oneshot) ──
cat > /etc/systemd/system/agora-topup.service <<UNIT
[Unit]
Description=Agora swarm auto-topup — refills poor buyers, rebalances rich providers
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$SWARM
ExecStart=/opt/agora/apps/backend/.venv/bin/python3 $SWARM/topup.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agora-topup
UNIT

# ── systemd timer unit — every 15 minutes ──
cat > /etc/systemd/system/agora-topup.timer <<TIMER
[Unit]
Description=Agora swarm auto-topup timer (every 15 minutes)
Requires=agora-topup.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=1min
Unit=agora-topup.service

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable agora-topup.timer
systemctl start agora-topup.timer

# Fire one manual run right now so the swarm has fresh balances immediately
echo
echo "=== Initial run ==="
systemctl start agora-topup.service
sleep 8
journalctl -u agora-topup -n 30 --no-pager

echo
echo "=== Timer status ==="
systemctl status agora-topup.timer --no-pager | head -10

echo
echo "✅ Auto-topup timer installed."
echo "   View live runs:    journalctl -u agora-topup -f"
echo "   Force a run now:   systemctl start agora-topup.service"
echo "   Disable:           systemctl disable --now agora-topup.timer"
