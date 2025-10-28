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

# 3) 섹션별 복구 (화이트리스트 스키마만)
echo "🧱 PRE-DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=pre-data --schema="$S" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/pre-data.log"
done

echo "📥 DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=data --schema="$S" -j "$JOBS" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/data.log"
done

echo "🔩 POST-DATA..."
for S in $SCHEMAS; do
  pg_restore --no-owner --no-privileges --section=post-data --schema="$S" -j "$JOBS" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee -a "$LOG_DIR/post-data.log"
done

# 4) 부모 INDEX/FK 보정 (실패 허용)
echo "🔎 Checking parent indexes/constraints..."
MISSING=$($PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "
WITH h AS (
  SELECT (hypertable_schema||'.'||hypertable_name) AS rel
  FROM timescaledb_information.hypertables
),
idx AS (
  SELECT (schemaname||'.'||tablename) AS rel, COUNT(*) AS idx_cnt
  FROM pg_indexes WHERE schemaname='public' GROUP BY 1
),
fk AS (
  SELECT c.conrelid::regclass::text AS rel, COUNT(*) AS fk_cnt
  FROM pg_constraint c WHERE c.contype='f' GROUP BY 1
)
SELECT COUNT(*) FROM (
  SELECT h.rel,
         COALESCE(i.idx_cnt,0) AS i,
         COALESCE(f.fk_cnt,0) AS f
  FROM h LEFT JOIN idx i ON i.rel=h.rel LEFT JOIN fk f ON f.rel=h.rel
  WHERE COALESCE(i.idx_cnt,0)=0 OR COALESCE(f.fk_cnt,0)=0
) s;")

if [ "${MISSING:-0}" -ne 0 ]; then
  echo "⚠️ Replaying parent public INDEX/FK from dump (soft-fail allowed)..."
  TOC=/tmp/parent.ic
  pg_restore -l "$DUMP_PATH" \
    | grep -E "^(;| ).*( INDEX | FK CONSTRAINT ).* public " > "$TOC" || true

  if [ -s "$TOC" ]; then
    set +e
    pg_restore --no-owner --no-privileges --use-list="$TOC" \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_PATH" | tee "$LOG_DIR/parent-ic.log"
    RC=$?
    set -e
    [ $RC -ne 0 ] && echo "⚠️ parent INDEX/FK replay returned ${RC} — continuing. See $LOG_DIR/parent-ic.log"
  else
    echo "ℹ️ No public INDEX/FK lines found in TOC."
  fi
else
  echo "✅ Parent indexes/constraints look present."
fi

# 5) post-restore 훅 (청크 인덱스/제약 생성)
echo "🧯 timescaledb_post_restore()..."
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_post_restore();"

# 6) 검증 (버전별 뷰 유무 대응)
echo "🔎 Hypertables & chunks:"
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT hypertable_schema, hypertable_name, num_chunks
   FROM timescaledb_information.hypertables
   ORDER BY 1,2;"

HAS_VIEW=$($PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
"SELECT to_regclass('timescaledb_information.chunk_indexes') IS NOT NULL;")
if [ "$HAS_VIEW" = "t" ]; then
  $PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT c.schema_name, c.table_name, i.index_name
     FROM timescaledb_information.chunk_indexes i
     JOIN timescaledb_information.chunks c ON c.chunk_table = i.chunk_table
     ORDER BY 1,2,3 LIMIT 20;"
else
  $PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT n.nspname AS schema_name, c.relname AS chunk_table, i.relname AS index_name
     FROM pg_class i
     JOIN pg_index ix ON ix.indexrelid=i.oid
     JOIN pg_class c  ON ix.indrelid=c.oid
     JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='_timescaledb_internal' AND c.relname LIKE '_hyper_%'
    ORDER BY 1,2,3 LIMIT 20;"
fi

echo "📊 ANALYZE"
$PSQL -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ANALYZE;"

echo "✅ Restore complete."
echo "🗒  Logs: ${LOG_DIR}"
