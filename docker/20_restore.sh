#!/bin/sh
set -e

echo "📦 Restoring PostgreSQL dump into database: ${POSTGRES_DB}"

PSQL="psql -X -v ON_ERROR_STOP=1 -U ${POSTGRES_USER}"
DUMP_PATH="/docker-entrypoint-initdb.d/trader.dump"
LIST_PATH="/tmp/trader.list"
LOG_PATH="/tmp/pg_restore.log"

# 0) preload 라이브러리 확인(옵션)
$PSQL -d postgres -c "SHOW shared_preload_libraries;"

# 1) 확장 설치 (컨테이너에 설치된 버전 사용)
$PSQL -d "${POSTGRES_DB}" <<-'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
SQL

# 2) Timescale pre-restore 훅
$PSQL -d "${POSTGRES_DB}" -c "SELECT timescaledb_pre_restore();"

# 3) 덤프 리스트 생성 후 불필요 항목 제거
echo "📝 Building filtered restore list (exclude EXTENSION, headers, _timescaledb_* schemas)"
pg_restore -l "${DUMP_PATH}" > "${LIST_PATH}"

# BusyBox 호환: sed -I 대신 grep 파이프
grep -vi ' EXTENSION ' "${LIST_PATH}" \
  | grep -viE '(ENCODING|STDSTRINGS|SEARCHPATH|DATABASE)' \
  | grep -viE ' _timescaledb_(catalog|internal|config) ' \
  > "${LIST_PATH}.filtered"

mv "${LIST_PATH}.filtered" "${LIST_PATH}"

# 4) 복원 실행 (단일 스레드: post-data 락 경합 최소화)
echo "🔧 Running pg_restore with filtered list (skip EXTENSION & _timescaledb_*), -j 1"
pg_restore \
  --no-owner --no-privileges \
  --use-list="${LIST_PATH}" \
  --exclude-schema=_timescaledb_catalog \
  --exclude-schema=_timescaledb_internal \
  --exclude-schema=_timescaledb_config \
  --exit-on-error \
  -j 1 \
  -v \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  "${DUMP_PATH}" \
  > "${LOG_PATH}" 2>&1

# 5) Timescale post-restore 훅
$PSQL -d "${POSTGRES_DB}" -c "SELECT timescaledb_post_restore();"

echo "✅ Database restore complete."

# 6) 간단 검증 (인덱스/제약 개수)
$PSQL -d "${POSTGRES_DB}" -c \
  "SELECT 'indexes' AS kind, count(*) FROM pg_indexes WHERE schemaname='public'
   UNION ALL
   SELECT 'constraints', count(*) FROM pg_constraint c
     JOIN pg_namespace n ON n.oid=c.connamespace
    WHERE n.nspname='public';"

echo "🗒  Detailed log: ${LOG_PATH}"
