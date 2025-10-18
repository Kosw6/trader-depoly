#!/bin/sh
set -e

echo "📦 Restoring PostgreSQL dump into database: ${POSTGRES_DB}"

# 확장 먼저 설치
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<-'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
SQL

# 대용량 복원 (트리거 비활성화 + 병렬)
pg_restore --disable-triggers --no-owner --no-privileges \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  /docker-entrypoint-initdb.d/trader.dump

echo "✅ Database restore complete."
