-- Runs once, on the first start of an empty volume. Same layout as RDS:
-- `dash` (POSTGRES_DB) with pgvector, plus a separate `nango` database.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE nango;
