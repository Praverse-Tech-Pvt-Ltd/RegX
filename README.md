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

## Security baseline

See [docs/SECURITY_BASELINE.md](docs/SECURITY_BASELINE.md).

## Legacy boundary

This codebase (`regx-main` branch) is a clean-room implementation.
It shares no code with the legacy booking demo on the `main` branch.
See [docs/LEGACY_BOUNDARY.md](docs/LEGACY_BOUNDARY.md).
