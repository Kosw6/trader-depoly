#!/bin/sh
set -e

echo "📦 Restoring PostgreSQL dump into database: ${POSTGRES_DB}"

PSQL="psql -X -v ON_ERROR_STOP=1 -U ${POSTGRES_USER}"

# 0) preload 라이브러리 확인(옵션)
$PSQL -d postgres -c "SHOW shared_preload_libraries;"

# 1) 확장 설치 (Timescale 먼저)
$PSQL -d "${POSTGRES_DB}" <<-'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL

# 2) Timescale pre-restore 훅
$PSQL -d "${POSTGRES_DB}" -c "SELECT timescaledb_pre_restore();"

# 3) 본 복원 (Custom 포맷 .dump)
pg_restore \
  --no-owner --no-privileges \
  --exit-on-error \
  -j "${PG_RESTORE_JOBS:-4}" \
  -v \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  /docker-entrypoint-initdb.d/trader.dump | tee /tmp/pg_restore.log

# 4) Timescale post-restore 훅
$PSQL -d "${POSTGRES_DB}" -c "SELECT timescaledb_post_restore();"

echo "✅ Database restore complete."

# (선택) 간단 검증
$PSQL -d "${POSTGRES_DB}" -c "SELECT hypertable_schema, hypertable_name, num_chunks FROM timescaledb_information.hypertables ORDER BY 1,2;"
$PSQL -d "${POSTGRES_DB}" -c "SELECT hypertable_name, count(*) AS chunks FROM timescaledb_information.chunks GROUP BY 1 ORDER BY 1;"
