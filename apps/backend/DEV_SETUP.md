# Backend Dev Setup

The Agora backend lives under `apps/backend/`. This document covers
the steps to run the test suite (and lint) on a fresh dev machine.

## Verified versions

| Where | Python | pytest | Status |
|---|---|---|---|
| CI (GitHub Actions) | 3.11 | 8.2+ | green, 137 tests pass |
| Server (`agora-1`) | 3.12.3 | 9.0.3 | green, 137 tests pass |
| Local dev | 3.11+ recommended | (from `[dev]` extras) | follow below |

## Prerequisites

- **Python 3.11+** (project's `pyproject.toml` requires `>=3.11`)
- **git**
- A POSIX shell for the `Makefile` shortcuts (Linux, macOS, WSL,
  Git-Bash). Native PowerShell works fine for the manual commands too
  — see the Windows section.

## Quick start (Linux / macOS / WSL / Git-Bash)

From the repo root:

```bash
cd apps/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=src pytest
```

You should see `137 passed in <N>s`.

Or with the convenience `Makefile`:

```bash
cd apps/backend
make install
make test
```

## Quick start (Windows PowerShell, no Git-Bash)

```powershell
cd apps\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:PYTHONPATH = "src"
pytest
```

If `py -3.11` errors with "Requested Python version not installed",
grab Python 3.11+ from <https://www.python.org/downloads/> — during
install, tick **"Add python.exe to PATH"** so `py` finds it.

After install you can verify in a fresh PowerShell:

```powershell
py -3.11 --version    # → Python 3.11.x
```

## Running a single test file

```bash
PYTHONPATH=src pytest tests/test_rfq.py -v
PYTHONPATH=src pytest tests/test_escrow_dispatch.py -v
PYTHONPATH=src pytest tests/test_chain_watcher_filter.py -v
```

Or via Make:

```bash
make test-rfq
make test-escrow
make test-watcher
```

## Lint

```bash
ruff check .
ruff check --fix .   # auto-fix what's safely auto-fixable
```

Or:

```bash
make lint
make lint-fix
```

## CI parity

The exact commands CI runs (see `.github/workflows/ci.yml`):

```bash
pip install -e ".[dev]"
pip install -e ../../packages/sdk-python   # the Python SDK is a separate package
ruff check .
PYTHONPATH=src pytest -v
```

If you want full CI parity locally including the SDK install:

```bash
make install-with-sdk
make ci      # ruff + pytest, same flags as CI
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'agora_api'`

You either forgot `PYTHONPATH=src` or you're not in `apps/backend/`.
The project uses the `src/` layout; the package isn't importable until
you either editable-install (`pip install -e .`) or set `PYTHONPATH`.
Editable install + PYTHONPATH both work; CI uses both as
belt-and-suspenders.

### `Python: command not found` or wrong version

```bash
python --version   # Linux/macOS
py --version       # Windows
```

If it's < 3.11, use `python3.11` / `py -3.11` explicitly, or install
a newer Python.

### Test passes locally but fails in CI (or vice versa)

Almost always a Python version mismatch. CI uses 3.11, server uses
3.12, your laptop might be 3.10 or 3.13. Match CI to be safe.

### Tests are slow / hang

The test suite uses **in-memory SQLite per test** (see `conftest.py`),
not the real PostgreSQL. If you ever see a `connection refused` or
similar, you accidentally pulled in a fixture that talks to real
infra. The CI runs the suite in < 10 s.

### `pyproject.toml` parse error

This file has historically been truncated by a sandbox mount-lag bug
(Sprint 28b, Sprint 34e). If pip complains, validate with:

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
```

If that errors, restore from the last green commit:

```bash
git checkout sprint-34e-pyproject-repair -- apps/backend/pyproject.toml
```

## What the test suite covers (orientation)

| File | Subject |
|---|---|
| `test_health.py` | `/health`, `/v1/state` |
| `test_agents.py` | `POST /v1/agents/register`, identity flow |
| `test_auth.py` | Ed25519 + Privy auth |
| `test_jobs.py` | Off-chain ledger jobs |
| `test_listings.py` | Marketplace listings CRUD |
| `test_pricing.py` | House rule: ≤ 0.01 USDC per listing |
| `test_reviews.py` | Post-job review flow |
| `test_rfq.py` | RFQ requests + signed bids (Sprint 31, 34a-d) + losing-bid lifecycle (Sprint 36e) + replay protection (Sprint 36d) |
| `test_escrow_dispatch.py` | V1/V2 ABI dispatch in `AgoraEscrowClient` (Sprint 36c) |
| `test_chain_watcher_filter.py` | Watcher skips legacy V1 jobs (Sprint 36g) |
| `test_search.py` | Capability + free-text search |
| `test_stats.py` | `/v1/stats` aggregates |
| `test_webhook_*.py` | Webhook signing, delivery, signing roundtrip |
| `test_x402_endpoint.py` | HTTP 402 escrow lifecycle |
