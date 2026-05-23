#!/bin/bash
# Sprint 13: Deploy the swarm onto agora-1 as a systemd service.
# Run this ONCE on the server (root@188.245.39.250) after `git pull`.
# Uses the master seed from the original sandbox bootstrap so derived
# wallets match the already-registered DIDs and already-funded balances.

set -e

cd /opt/agora/experiments/swarm
mkdir -p data
chmod 700 data

echo "=== Writing master_seed.txt (used to derive 20 agent wallets) ==="
cat > data/master_seed.txt <<'SEED'
bf2ea31de49bd7dcb94a7368957d38274b10925aa3265bc8d37a54f4c8984a71
SEED
chmod 600 data/master_seed.txt

echo "=== Writing dids.json (the agents already registered on Agora) ==="
cat > data/dids.json <<'DIDS'
{
  "translator-en-de": "did:agora:swarm-109d32fca1e9440d",
  "summarizer": "did:agora:swarm-c82f5b0475a37178",
  "sentiment": "did:agora:swarm-3e8e5c4742648319",
  "joke-maker": "did:agora:swarm-f8556c6276b12d59",
  "code-reviewer": "did:agora:swarm-05850e20f45a450e",
  "fact-checker": "did:agora:swarm-966d5da20d1c8ae2",
  "tarot-reader": "did:agora:swarm-4842c1fa08649fd5",
  "image-describer": "did:agora:swarm-49d858323206a3db",
  "idea-generator": "did:agora:swarm-1f7288c5041b4208",
  "rhyme-maker": "did:agora:swarm-114fc19c49963b57",
  "marketing-alice": "did:agora:swarm-3bb89fb587a85b2c",
  "dev-bob": "did:agora:swarm-b6add1b4f2d0ad75",
  "writer-carl": "did:agora:swarm-7a27ef5721b42f64",
  "teacher-dana": "did:agora:swarm-c553e89c9a211b24",
  "social-eva": "did:agora:swarm-fc92573d00ce34df",
  "novelist-fred": "did:agora:swarm-e2e7c42feea273ac",
  "insight-greg": "did:agora:swarm-1f3d34f67a2ce494",
  "consultant-helga": "did:agora:swarm-17d0dfd7d75cbbf6",
  "entrepreneur-ingrid": "did:agora:swarm-0c314662e2c433e6",
  "streamer-joe": "did:agora:swarm-0076ffa4b760ddf0"
}
DIDS
chmod 600 data/dids.json

echo "=== Activating venv + ensuring agora-sdk is installed ==="
source /opt/agora/apps/backend/.venv/bin/activate
pip install -e /opt/agora/packages/sdk-python --quiet || true

echo "=== Deriving wallets from master seed (deterministic, matches the running swarm) ==="
python3 wallet_setup.py --gen
chmod 600 data/wallets.json

echo "=== Verifying current on-chain balances ==="
python3 wallet_setup.py --verify | head -25

echo "=== Writing service env file (Anthropic key) ==="
# Pull the Anthropic key from the main agora .env (already configured there
# manually by the operator before running this script).
ANTHROPIC=$(grep '^ANTHROPIC_API_KEY=' /opt/agora/apps/backend/.env | cut -d= -f2-)
if [ -z "$ANTHROPIC" ]; then
    echo "WARNING: ANTHROPIC_API_KEY not found in /opt/agora/apps/backend/.env"
    echo "Set it there before starting the service or the LLM calls will stub."
fi
cat > /opt/agora/experiments/swarm/.env <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC
PYTHONUNBUFFERED=1
EOF
chmod 600 /opt/agora/experiments/swarm/.env

echo "=== Creating systemd unit ==="
cat > /etc/systemd/system/agora-swarm.service <<'UNIT'
[Unit]
Description=Agora 20-agent autonomous swarm (Sprint 13)
After=network.target agora-api.service
Wants=agora-api.service

[Service]
Type=simple
WorkingDirectory=/opt/agora/experiments/swarm
EnvironmentFile=/opt/agora/experiments/swarm/.env
ExecStart=/opt/agora/apps/backend/.venv/bin/python3 /opt/agora/experiments/swarm/orchestrator.py
Restart=on-failure
RestartSec=15

# Send everything to journald — view with: journalctl -u agora-swarm -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agora-swarm

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable agora-swarm
systemctl restart agora-swarm
sleep 5

echo ""
echo "=== Service status ==="
systemctl status agora-swarm --no-pager | head -15

echo ""
echo "=== Last 20 log lines ==="
journalctl -u agora-swarm --no-pager -n 20

echo ""
echo "✅ Swarm deployed. Watch live: journalctl -u agora-swarm -f"
echo "Stop:                          systemctl stop agora-swarm"
echo "Restart:                       systemctl restart agora-swarm"
