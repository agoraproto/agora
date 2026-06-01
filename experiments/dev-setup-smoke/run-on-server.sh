#!/usr/bin/env bash
# Sprint 38a — Prove the 3 named tests run green on the server venv.
# Also re-sync dev deps in case pyproject.toml drifted since last install.

VENV=/opt/agora/apps/backend/.venv

cd /opt/agora/apps/backend

echo "============================================================"
echo "  Backend pytest smoke test  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"

echo ""
echo "=== Versions ==="
echo -n "  Python:       "; $VENV/bin/python3 --version
echo -n "  pytest:       "; $VENV/bin/pytest --version 2>&1 | head -1
echo -n "  Project root: "; pwd
echo -n "  pyproject:    "; head -3 pyproject.toml

echo ""
echo "=== Re-sync dev deps (idempotent) ==="
$VENV/bin/pip install -q -e ".[dev]" 2>&1 | tail -4
echo "  + dev deps in sync"

echo ""
echo "=== The 3 named tests ==="
PYTHONPATH=src $VENV/bin/pytest \
    tests/test_rfq.py \
    tests/test_escrow_dispatch.py \
    tests/test_chain_watcher_filter.py \
    -v --tb=short 2>&1 | tail -45

echo ""
echo "=== Full backend test suite (count) ==="
PYTHONPATH=src $VENV/bin/pytest -q --tb=no 2>&1 | tail -3

echo ""
echo "=== agora-api still alive? ==="
systemctl is-active agora-api
curl -s -o /dev/null -w "  /v1/state HTTP %{http_code}\n" https://api.agoraproto.org/v1/state

echo ""
echo "============================================================"
echo "  Done."
echo "============================================================"
