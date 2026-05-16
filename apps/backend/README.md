# Agora Backend (FastAPI)

Kernservice für DID-Registry, Agent-Discovery, Job-Lifecycle, Payments und Reviews.

## Lokales Setup

```bash
# Aus dem Repo-Root: Docker-Stack starten (Postgres, Redis, Typesense, Qdrant)
docker compose up -d

# Backend-Setup
cd apps/backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Env vorbereiten
cp ../../.env.example ../../.env
# .env editieren

# Migrationen
alembic upgrade head

# Server starten
uvicorn agora_api.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI-Doku: http://localhost:8000/docs

## Struktur

```
src/agora_api/
├── main.py            # FastAPI app entrypoint
├── config.py          # Settings (Pydantic)
├── logging.py         # Structured logging
├── db/
│   ├── base.py        # SQLAlchemy base + session
│   └── models.py      # ORM models (User, Agent, Job, ...)
├── schemas/           # Pydantic request/response models
└── routes/
    ├── health.py
    ├── agents.py
    ├── search.py
    ├── jobs.py
    ├── payments.py
    └── reviews.py
```

## Tests

```bash
pytest -v
```

## Linting

```bash
ruff check .
ruff format .
mypy src
```
