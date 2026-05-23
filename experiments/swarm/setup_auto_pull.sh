#!/bin/bash
# Sprint 17 — server-side auto-pull timer.
#
# Installs a systemd-timer that fires every 30 seconds:
#   1. Fetches origin/main.
#   2. If there are new commits, runs `git pull`.
#   3. Detects which services are affected by the change and restarts
#      only those:
#        - apps/backend/**   → agora-api
#        - apps/website/**   → caddy reload (cheap)
#        - experiments/swarm/agents/** or personalities.py → agora-swarm
#        - everything else → no restart
#
# Result: once Andreas has set this up, every git push automatically
# rolls out to production within 30 seconds. No more ssh + git pull +
# systemctl restart by hand.

set -e

cat > /etc/systemd/system/agora-autopull.service <<'UNIT'
[Unit]
Description=Agora auto-pull and surgical restart
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/agora
ExecStart=/opt/agora/experiments/swarm/auto_pull_step.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agora-autopull
UNIT

cat > /etc/systemd/system/agora-autopull.timer <<'TIMER'
[Unit]
Description=Agora auto-pull timer (every 30s)
Requires=agora-autopull.service

[Timer]
OnBootSec=15s
OnUnitActiveSec=30s
AccuracySec=5s
Unit=agora-autopull.service

[Install]
WantedBy=timers.target
TIMER

# The pull-step worker
cat > /opt/agora/experiments/swarm/auto_pull_step.sh <<'WORKER'
#!/bin/bash
set -e
cd /opt/agora

# Discard any local mode-bit changes (chmod +x etc.) so git pull never trips.
git checkout -- . 2>/dev/null || true

# Fetch + see if we're behind
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0   # nothing to do, silent
fi

echo "auto-pull: behind by $(git rev-list --count $LOCAL..$REMOTE) commit(s); pulling…"
CHANGED=$(git diff --name-only $LOCAL $REMOTE)
git pull --quiet

# Surgical restart based on what changed
restart_api=0
restart_swarm=0
reload_caddy=0
for f in $CHANGED; do
    case "$f" in
        apps/backend/*) restart_api=1 ;;
        apps/website/*) reload_caddy=1 ;;
        experiments/swarm/agents/*|experiments/swarm/personalities.py|experiments/swarm/orchestrator.py|experiments/swarm/lib/*) restart_swarm=1 ;;
    esac
done

if [ $restart_api -eq 1 ]; then
    echo "auto-pull: restarting agora-api…"
    systemctl restart agora-api
fi
if [ $restart_swarm -eq 1 ]; then
    echo "auto-pull: restarting agora-swarm…"
    systemctl restart agora-swarm
fi
if [ $reload_caddy -eq 1 ]; then
    # static HTML is symlinked, but new symlinks may be needed
    for f in $CHANGED; do
        if [[ "$f" =~ ^apps/website/(.+\.html)$ ]]; then
            BASE="${BASH_REMATCH[1]}"
            if [ ! -e "/var/www/agoraproto.org/$BASE" ]; then
                ln -sf "/opt/agora/apps/website/$BASE" "/var/www/agoraproto.org/$BASE"
                echo "auto-pull: created symlink for new html file: $BASE"
            fi
        fi
    done
    # Caddy serves from disk; no reload needed for content changes.
fi

echo "auto-pull: done."
WORKER
chmod +x /opt/agora/experiments/swarm/auto_pull_step.sh

systemctl daemon-reload
systemctl enable agora-autopull.timer
systemctl start agora-autopull.timer

echo ""
echo "✅ Auto-pull-timer installed."
echo "   View live runs: journalctl -u agora-autopull -f"
echo "   Force a run:    systemctl start agora-autopull.service"
echo "   Disable:        systemctl disable --now agora-autopull.timer"
echo ""
echo "From now on:"
echo "  Andreas (or Claude with PAT) pushes to origin/main."
echo "  Within 30 seconds the server pulls and restarts only affected services."
echo "  No manual 'ssh + git pull + systemctl restart' ever again."
