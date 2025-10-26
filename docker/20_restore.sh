#!/bin/sh
set -e

echo "📦 Restoring PostgreSQL dump into database: ${POSTGRES_DB}"

# 0) 확장 선로딩 확인용 출력 (옵션)
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d postgres -c "SHOW shared_preload_libraries;"

# 1) 대상 DB에 확장 설치 (Timescale 반드시 선행)
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<-'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
SQL

# 2) Timescale pre-restore 훅 (메타 복원 준비)
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT public.timescaledb_pre_restore();"

# 3) 본 복원 (Custom 포맷 .dump 권장, 병렬 옵션은 CPU/IO에 맞게 조정)
#    --disable-triggers 유지 가능(대용량 빠름). owner/privileges는 덤프 내용에 따라 조정.
pg_restore \
  --disable-triggers \
  --no-owner --no-privileges \
  --jobs=${PG_RESTORE_JOBS:-4} \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  /docker-entrypoint-initdb.d/trader.dump

# 4) Timescale post-restore 훅 (메타 정합성 마무리)
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT public.timescaledb_post_restore();"

echo "✅ Database restore complete."
