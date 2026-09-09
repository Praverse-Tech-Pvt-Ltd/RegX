# REGX

Regulatory workflow management platform.

## Quick start

```bash
cp .env.example .env
# Edit .env with real values
python scripts/check_env.py

# Start services
docker compose up --build
```

Backend: http://localhost:8000  
API docs: http://localhost:8000/api/docs/  
Frontend: http://localhost:3000

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Picking up in-progress work on this branch: start with
[`test-checklist.md`](test-checklist.md), then [`handoff.md`](handoff.md),
[`constraints.md`](constraints.md) and [`decisions.md`](decisions.md).

One account signs in to both applications — the legacy company login delegates
to REGX auth. See
[docs/COMPANY_SITE_AUTH_INTEGRATION.md](docs/COMPANY_SITE_AUTH_INTEGRATION.md).

## Security baseline

See [docs/SECURITY_BASELINE.md](docs/SECURITY_BASELINE.md).

## Legacy boundary

This codebase (`regx-main` branch) is a clean-room implementation.
It shares no code with the legacy booking demo on the `main` branch.
See [docs/LEGACY_BOUNDARY.md](docs/LEGACY_BOUNDARY.md).
