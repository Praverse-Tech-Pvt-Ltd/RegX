# Development Guide

## Requirements

- Python 3.12+
- Node.js 22+
- Rancher Desktop (or Docker) with a running daemon
- PostgreSQL 16 (via Docker)

## Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

cp ../.env.example ../.env  # fill in values
python ../scripts/check_env.py

python manage.py migrate
python manage.py runserver
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

## Run tests

```bash
cd backend
pytest
```

## Lint

```bash
cd backend
ruff check .
ruff format --check .
lint-imports
```

## Docker (full stack)

```bash
cp .env.example .env  # fill in values
docker compose up --build
```
