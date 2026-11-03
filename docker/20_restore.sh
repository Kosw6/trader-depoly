#!/bin/sh
# /docker-entrypoint-initdb.d/20_restore.sh
# PostgreSQL 17 + TimescaleDB (카탈로그 포함, internal은 제외) — 견고화 버전

set -euo pipefail

echo "📦 Restoring dump into database: ${POSTGRES_DB}"

PSQL='psql -X -v ON_ERROR_STOP=1'
: "${POSTGRES_USER:?}"; : "${POSTGRES_DB:?}"
DUMP_PATH="${DUMP_PATH:-/docker-entrypoint-initdb.d/trader.dump}"
LOG_DIR="/tmp/pg_restore_logs"; mkdir -p "$LOG_DIR"
JOBS="${RESTORE_JOBS:-1}"
SCHEMAS="public _timescaledb_catalog"   # 필요하면 사용자 스키마 더 추가

[ -f "$DUMP_PATH" ] || { echo "❌ Dump not found: $DUMP_PATH"; exit 1; }

echo "    shared_preload_libraries:"
$PSQL -U "$POSTGRES_USER" -d postgres -c "SHOW shared_preload_libraries;"

# 1) 확장 설치 (업데이트는 수행하지 않음)
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL

# 2) pre-restore 훅
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_pre_restore();"

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
