#!/bin/sh
set -euo pipefail

echo "📦 Restoring dump into database: ${POSTGRES_DB}"

PSQL='psql -X -v ON_ERROR_STOP=1'
: "${POSTGRES_USER:?}"; : "${POSTGRES_DB:?}"
DUMP_PATH="${DUMP_PATH:-/docker-entrypoint-initdb.d/trader.dump}"
LOG_DIR="/tmp/pg_restore_logs"; mkdir -p "$LOG_DIR"

# ✅ 복원 대상 스키마: 유저 스키마 + 청크 스키마만
SCHEMAS="public _timescaledb_internal"   # ← _timescaledb_catalog 빼기!
JOBS="${RESTORE_JOBS:-4}"

[ -f "$DUMP_PATH" ] || { echo "❌ Dump not found: $DUMP_PATH"; exit 1; }

echo "    shared_preload_libraries:"
$PSQL -U "$POSTGRES_USER" -d postgres -c "SHOW shared_preload_libraries;"

# 1) 확장 설치
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL

# 2) pre-restore 훅
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_pre_restore();"

# 3) PRE-DATA (정의)
echo "🧱 PRE-DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=pre-data --schema="$S" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/pre-data.log"
done

# 4) DATA (실제 레코드)  ← 병렬 OK
echo "📥 DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=data --schema="$S" -j "$JOBS" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/data.log"
done

# 5) POST-DATA (인덱스/제약)
echo "🔩 POST-DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=post-data --schema="$S" -j "$JOBS" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/post-data.log"
done

# 6) post-restore 훅 → 카탈로그 자동 재구성
echo "🧯 timescaledb_post_restore()..."
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_post_restore();"

# 7) 검증
echo "🔎 Hypertables & chunks:"
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT hypertable_schema, hypertable_name, num_chunks
   FROM timescaledb_information.hypertables
   ORDER BY 1,2;"

$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT chunk_schema, chunk_name
   FROM timescaledb_information.chunks
   ORDER BY 1,2 LIMIT 20;"

echo "📊 ANALYZE"
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ANALYZE;"

echo "✅ Restore complete."
echo "🗒  Logs: ${LOG_DIR}"
