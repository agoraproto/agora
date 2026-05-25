#!/bin/bash
# Sprint 20 — Deploy the Audit Document Gap Checker as a systemd service.
#
# Run on the server (root@agora-1) after the auto-pull-timer has picked
# up the new experiments/audit_agent/ folder. Idempotent: if credentials
# + listing already exist, the bootstrap is skipped and only the service
# is (re)installed.

set -e

AUDIT="/opt/agora/experiments/audit_agent"
SWARM_ENV="/opt/agora/experiments/swarm/.env"
VENV_PY="/opt/agora/apps/backend/.venv/bin/python3"

cd "$AUDIT"

echo "=== Sanity check ==="
[ -d "$AUDIT" ] || { echo "❌ $AUDIT missing — did auto-pull run?"; exit 1; }
[ -f "$AUDIT/system_prompt.md" ] || { echo "❌ system_prompt.md missing"; exit 1; }
[ -f "$AUDIT/register.py" ] || { echo "❌ register.py missing"; exit 1; }
[ -f "$AUDIT/agent.py" ] || { echo "❌ agent.py missing"; exit 1; }
[ -x "$VENV_PY" ] || { echo "❌ $VENV_PY missing"; exit 1; }

echo "=== Ensure data/ dir ==="
mkdir -p data
chmod 700 data

echo "=== Ensure agora-sdk is installed in the backend venv ==="
"$VENV_PY" -m pip install -e /opt/agora/packages/sdk-python --quiet || true

echo "=== Bootstrap agent (POST /v1/agents/bootstrap) if needed ==="
# register.py is idempotent — it reuses data/credentials.json if present.
"$VENV_PY" register.py

echo "=== Resolve ANTHROPIC_API_KEY source ==="
if [ -f "$SWARM_ENV" ]; then
    ENV_FILE="$SWARM_ENV"
    echo "  reusing $SWARM_ENV"
elif [ -f "$AUDIT/.env" ]; then
    ENV_FILE="$AUDIT/.env"
    echo "  using local $AUDIT/.env"
else
    echo "  ⚠  Neither $SWARM_ENV nor $AUDIT/.env found — the audit agent will run"
    echo "      but every job will return the stub response until ANTHROPIC_API_KEY"
    echo "      is set. Add it to /opt/agora/experiments/audit_agent/.env (mode 600)."
    cat > "$AUDIT/.env" <<EOF
# Add your Anthropic key here:
# ANTHROPIC_API_KEY=sk-ant-...
PYTHONUNBUFFERED=1
EOF
    chmod 600 "$AUDIT/.env"
    ENV_FILE="$AUDIT/.env"
fi

echo "=== Install systemd unit ==="
cat > /etc/systemd/system/agora-audit-agent.service <<UNIT
[Unit]
Description=Agora Audit Document Gap Checker (Sprint 20)
After=network.target agora-api.service
Wants=agora-api.service

[Service]
Type=simple
WorkingDirectory=$AUDIT
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PY $AUDIT/agent.py
Restart=on-failure
RestartSec=10

# Send everything to journald — view with: journalctl -u agora-audit-agent -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agora-audit-agent

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable agora-audit-agent
systemctl restart agora-audit-agent
sleep 4

echo ""
echo "=== Service status ==="
systemctl status agora-audit-agent --no-pager | head -15

echo ""
echo "=== Last 15 log lines ==="
journalctl -u agora-audit-agent --no-pager -n 15

echo ""
echo "=== Audit agent identity ==="
"$VENV_PY" register.py --print || true

echo ""
echo "✅ Audit agent deployed."
echo "   Watch live:    journalctl -u agora-audit-agent -f"
echo "   Stop:          systemctl stop agora-audit-agent"
echo "   Recreate listing: cd $AUDIT && $VENV_PY register.py --listing"
