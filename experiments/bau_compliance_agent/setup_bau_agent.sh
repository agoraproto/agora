#!/bin/bash
# Sprint 21 — Deploy the Bau-Compliance Agent as a systemd service.
#
# Run on the server (root@agora-1) after the auto-pull-timer has picked
# up experiments/bau_compliance_agent/. Idempotent: re-running just
# (re-)installs the systemd unit and restarts the service.

set -e

BAU="/opt/agora/experiments/bau_compliance_agent"
SWARM_ENV="/opt/agora/experiments/swarm/.env"
VENV_PY="/opt/agora/apps/backend/.venv/bin/python3"

cd "$BAU"

echo "=== Sanity check ==="
[ -d "$BAU" ] || { echo "❌ $BAU missing — did auto-pull run?"; exit 1; }
[ -f "$BAU/system_prompt.md" ] || { echo "❌ system_prompt.md missing"; exit 1; }
[ -f "$BAU/register.py" ] || { echo "❌ register.py missing"; exit 1; }
[ -f "$BAU/agent.py" ] || { echo "❌ agent.py missing"; exit 1; }
[ -x "$VENV_PY" ] || { echo "❌ $VENV_PY missing"; exit 1; }

echo "=== Ensure data/ dir ==="
mkdir -p data
chmod 700 data

echo "=== Ensure agora-sdk is installed in the backend venv ==="
"$VENV_PY" -m pip install -e /opt/agora/packages/sdk-python --quiet || true

echo "=== Bootstrap agent (POST /v1/agents/bootstrap) if needed ==="
"$VENV_PY" register.py

echo "=== Resolve ANTHROPIC_API_KEY source ==="
if [ -f "$SWARM_ENV" ]; then
    ENV_FILE="$SWARM_ENV"
    echo "  reusing $SWARM_ENV"
elif [ -f "$BAU/.env" ]; then
    ENV_FILE="$BAU/.env"
    echo "  using local $BAU/.env"
else
    echo "  ⚠  Neither $SWARM_ENV nor $BAU/.env found — service will run with stub responses."
    cat > "$BAU/.env" <<EOF
# Add your Anthropic key here:
# ANTHROPIC_API_KEY=sk-ant-...
PYTHONUNBUFFERED=1
EOF
    chmod 600 "$BAU/.env"
    ENV_FILE="$BAU/.env"
fi

echo "=== Install systemd unit ==="
cat > /etc/systemd/system/agora-bau-agent.service <<UNIT
[Unit]
Description=Agora Bau-Compliance Agent (Sprint 21) — GEG/GMG/BEG/BAFA/KfW
After=network.target agora-api.service
Wants=agora-api.service

[Service]
Type=simple
WorkingDirectory=$BAU
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PY $BAU/agent.py
Restart=on-failure
RestartSec=10

# Send everything to journald — view with: journalctl -u agora-bau-agent -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agora-bau-agent

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable agora-bau-agent
systemctl restart agora-bau-agent
sleep 4

echo ""
echo "=== Service status ==="
systemctl status agora-bau-agent --no-pager | head -15

echo ""
echo "=== Last 15 log lines ==="
journalctl -u agora-bau-agent --no-pager -n 15

echo ""
echo "=== Bau agent identity ==="
"$VENV_PY" register.py --print || true

echo ""
echo "✅ Bau-Compliance Agent deployed."
echo "   Watch live:    journalctl -u agora-bau-agent -f"
echo "   Stop:          systemctl stop agora-bau-agent"
echo "   Fund wallet:   $VENV_PY $BAU/fund_wallet.py"
