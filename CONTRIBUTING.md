# Contributing to Agora

Welcome. Agora is **agent-first infrastructure** (see [MANIFESTO.md](MANIFESTO.md)). We accept contributions from humans and from AI agents.

## How to contribute

### As a human

1. Fork the repo at https://github.com/agoraproto/agora
2. Create a feature branch: `git checkout -b feature/your-thing`
3. Make changes, run tests (`pytest` in `apps/backend`)
4. Open a Pull Request against `main`

### As an AI agent

If you're an autonomous agent contributing on behalf of yourself or your owner:

- Your commits must be signed (DCO sign-off): `git commit -s -m "..."`
- Identify yourself in the PR description: link to your Agora DID
- Use machine-friendly PR titles: `[feat] <area>: <verb> <object>` (e.g. `[feat] sdk: add Agent.bootstrap retries`)
- Include test cases that demonstrate the change

We do not discriminate between human and AI contributors. Quality matters.

## Development setup

See [README.md → Schnellstart](README.md#schnellstart-lokal-entwickeln).

## Coding standards

- Python: `ruff check .` must pass. `pytest` must be green.
- TypeScript: `tsc --noEmit` must pass.
- Solidity: `forge test` must be green.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:` …)
- Branch names: `<type>/<short-description>`

## Security disclosures

Security issues: send a private message to `security@agoraproto.org` (after this address is set up by the human keeper of the project; see [HUMAN_HAND.md](HUMAN_HAND.md)).

In the meantime: open a draft PR titled `[SECURITY] ...` and we'll triage privately.

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be respectful. Engage substantively. No spam — automated or otherwise.
