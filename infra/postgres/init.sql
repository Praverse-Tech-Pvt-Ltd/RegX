-- REGX PostgreSQL initialization
-- This runs once when the container is first created.
-- The database and user are already created by POSTGRES_DB / POSTGRES_USER env vars.

-- Enable pgcrypto for any future UUID generation at the DB level
CREATE EXTENSION IF NOT EXISTS pgcrypto;
