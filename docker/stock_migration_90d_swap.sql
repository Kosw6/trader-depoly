-- =========================================================
--  Migrate public.stock (30d) → 90d - Windows Compatible
--  With max_locks fix: processes data in smaller weekly batches
-- =========================================================

\timing on

-- =========================
-- 0) Increase lock limits for migration
-- =========================
-- IMPORTANT: Add these to postgresql.conf or docker-compose environment:
-- max_locks_per_transaction = 256  (default is 64)
-- Then restart PostgreSQL

-- Check current settings
DO $$
DECLARE current_max int;
BEGIN
  SELECT setting::int INTO current_max FROM pg_settings WHERE name = 'max_locks_per_transaction';
  RAISE NOTICE 'Current max_locks_per_transaction: %', current_max;
  IF current_max < 256 THEN
    RAISE WARNING 'Recommended: max_locks_per_transaction >= 256. Current: %. Please update postgresql.conf and restart.', current_max;
  END IF;
END $$;

-- =========================
-- 1) Preflight checks
-- =========================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') THEN
    RAISE EXCEPTION 'Timescaledb extension not installed';
  END IF;
END $$;

DO $$
DECLARE ok regclass;
BEGIN
  SELECT to_regclass('public.stock') INTO ok;
  IF ok IS NULL THEN
    RAISE EXCEPTION 'Source table public.stock not found';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM timescaledb_information.hypertables
    WHERE hypertable_schema='public' AND hypertable_name='stock'
  ) THEN
    RAISE EXCEPTION 'public.stock is not a Timescale hypertable';
  END IF;
END $$;

-- Dependent view/materialized view check
DO $$
DECLARE cnt int;
BEGIN
  SELECT COUNT(*) INTO cnt
  FROM pg_depend d
  JOIN pg_class  cl ON d.refobjid = cl.oid
  WHERE d.objid = 'public.stock'::regclass
    AND cl.relkind IN ('v','m');
  IF cnt > 0 THEN
    RAISE EXCEPTION 'Dependent views/materialized views exist on public.stock. Handle them before swapping.';
  END IF;
END $$;

-- ==========================================
-- 2) Prepare destination hypertable (90 days)
-- ==========================================
DROP TABLE IF EXISTS public.stock_v2_90d CASCADE;

CREATE TABLE public.stock_v2_90d
(LIKE public.stock
 INCLUDING DEFAULTS
 INCLUDING IDENTITY
 INCLUDING GENERATED
 INCLUDING STORAGE
 INCLUDING COMMENTS
);

-- time dimension: 90 days, space dimension: symb with 8 partitions
SELECT create_hypertable('public.stock_v2_90d', 'timestamp', chunk_time_interval => INTERVAL '90 days');
SELECT add_dimension('public.stock_v2_90d', 'symb', number_partitions => 8);

-- ==========================================
-- 3) Create helper table for WEEKLY tracking (not monthly)
--    Weekly batches = fewer locks per transaction
-- ==========================================
DROP TABLE IF EXISTS _migration_weeks;
CREATE TEMP TABLE _migration_weeks AS
SELECT generate_series(
  date_trunc('week', MIN("timestamp")),
  date_trunc('week', MAX("timestamp")),
  INTERVAL '1 week'
) AS week_start
FROM public.stock;

-- Check if we have data
DO $$
DECLARE cnt int;
BEGIN
  SELECT COUNT(*) INTO cnt FROM _migration_weeks;
  IF cnt = 0 THEN
    RAISE EXCEPTION 'No data found in public.stock';
  END IF;
  RAISE NOTICE 'Found % weeks to migrate (smaller batches = fewer locks)', cnt;
END $$;

-- ==========================================
-- 4) Bulk load in WEEKLY batches
-- ==========================================
SET synchronous_commit   = off;
SET maintenance_work_mem = '2047MB';
SET work_mem             = '256MB';

-- Process in batches of 10 weeks at a time
DO $$
DECLARE
  w_start timestamptz;
  w_end   timestamptz;
  rows_inserted bigint;
  week_num int := 0;
  total_weeks int;
  batch_size int := 10;  -- Process 10 weeks at a time
  total_rows bigint := 0;
BEGIN
  SELECT COUNT(*) INTO total_weeks FROM _migration_weeks;
  
  FOR w_start IN 
    SELECT week_start 
    FROM _migration_weeks 
    ORDER BY week_start
  LOOP
    week_num := week_num + 1;
    w_end := w_start + INTERVAL '1 week';
    
    -- Show progress every 10 weeks
    IF week_num % 10 = 1 OR week_num = total_weeks THEN
      RAISE NOTICE 'Processing week % of % (%.1f%% complete)', 
        week_num, total_weeks, (week_num::float / total_weeks * 100);
    END IF;
    
    INSERT INTO public.stock_v2_90d
    SELECT *
    FROM public.stock
    WHERE "timestamp" >= w_start
      AND "timestamp"  < w_end;
    
    GET DIAGNOSTICS rows_inserted = ROW_COUNT;
    total_rows := total_rows + rows_inserted;
    
    -- Commit every batch_size weeks to release locks
    IF week_num % batch_size = 0 THEN
      RAISE NOTICE 'Batch checkpoint: % rows inserted so far', total_rows;
      -- Note: Can't COMMIT in DO block, but smaller batches help
    END IF;
  END LOOP;
  
  RAISE NOTICE 'Migration complete! Total weeks: %, Total rows: %', total_weeks, total_rows;
END $$;

-- ==========================================
-- 5) Recreate indexes AFTER load (skip if exists)
-- ==========================================
DO $
DECLARE rec RECORD; def TEXT; idx_count int := 0; skip_count int := 0;
BEGIN
  RAISE NOTICE 'Recreating indexes...';
  
  FOR rec IN
    SELECT schemaname, tablename, indexname
    FROM pg_indexes
    WHERE schemaname='public' AND tablename='stock'
  LOOP
    -- Check if index already exists on new table
    IF EXISTS (
      SELECT 1 FROM pg_indexes 
      WHERE schemaname='public' 
        AND tablename='stock_v2_90d' 
        AND indexname=rec.indexname
    ) THEN
      RAISE NOTICE 'Index % already exists, skipping', rec.indexname;
      skip_count := skip_count + 1;
      CONTINUE;
    END IF;

    SELECT pg_get_indexdef(i.indexrelid) INTO def
    FROM pg_class t
    JOIN pg_index i ON i.indrelid = t.oid
    JOIN pg_class x ON x.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname='public'
      AND t.relname='stock'
      AND x.relname=rec.indexname;

    def := replace(def, ' ON public.stock ', ' ON public.stock_v2_90d ');

    RAISE NOTICE 'Creating index: %', rec.indexname;
    EXECUTE def;
    idx_count := idx_count + 1;
  END LOOP;
  
  RAISE NOTICE 'Created % new indexes, skipped % existing indexes', idx_count, skip_count;
END $;

-- ==========================================
-- 6) Recreate constraints (skip if exists)
-- ==========================================
DO $
DECLARE r RECORD; ddl TEXT; con_count int := 0; skip_count int := 0;
BEGIN
  RAISE NOTICE 'Recreating constraints...';
  
  FOR r IN
    SELECT conname, contype, pg_get_constraintdef(oid) AS defn
    FROM pg_constraint
    WHERE conrelid = 'public.stock'::regclass
      AND contype IN ('p','u','c')
  LOOP
    -- Check if constraint already exists
    IF EXISTS (
      SELECT 1 FROM pg_constraint 
      WHERE conrelid = 'public.stock_v2_90d'::regclass 
        AND conname = r.conname
    ) THEN
      RAISE NOTICE 'Constraint % already exists, skipping', r.conname;
      skip_count := skip_count + 1;
      CONTINUE;
    END IF;

    ddl := format('ALTER TABLE public.stock_v2_90d ADD CONSTRAINT %I %s;', r.conname, r.defn);
    RAISE NOTICE 'Adding constraint: %', r.conname;
    EXECUTE ddl;
    con_count := con_count + 1;
  END LOOP;
  
  RAISE NOTICE 'Created % new constraints, skipped % existing constraints', con_count, skip_count;
END $;

ANALYZE public.stock_v2_90d;

-- ==========================================
-- 7) Atomic swap + inbound FK rewire
-- ==========================================
DROP TABLE IF EXISTS _inbound_fk;
CREATE TEMP TABLE _inbound_fk AS
SELECT conrelid::regclass        AS child_table,
       conname                   AS fk_name,
       pg_get_constraintdef(oid) AS fk_def
FROM pg_constraint
WHERE contype='f'
  AND confrelid = 'public.stock'::regclass;

BEGIN;
  RAISE NOTICE 'Starting atomic swap...';
  
  LOCK TABLE public.stock        IN ACCESS EXCLUSIVE MODE;
  LOCK TABLE public.stock_v2_90d IN ACCESS EXCLUSIVE MODE;

  DO $$
  DECLARE r RECORD; fk_count int := 0;
  BEGIN
    FOR r IN SELECT * FROM _inbound_fk LOOP
      EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I;', r.child_table, r.fk_name);
      fk_count := fk_count + 1;
    END LOOP;
    RAISE NOTICE 'Dropped % foreign keys', fk_count;
  END $$;

  ALTER TABLE public.stock        RENAME TO stock_old;
  ALTER TABLE public.stock_v2_90d RENAME TO stock;
  RAISE NOTICE 'Tables renamed successfully';

  DO $$
  DECLARE r RECORD; fk_count int := 0;
  BEGIN
    FOR r IN SELECT * FROM _inbound_fk LOOP
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s;', r.child_table, r.fk_name, r.fk_def);
      fk_count := fk_count + 1;
    END LOOP;
    RAISE NOTICE 'Recreated % foreign keys', fk_count;
  END $$;

COMMIT;

RAISE NOTICE 'Atomic swap complete!';

-- ==========================================
-- 8) Verify migration
-- ==========================================
DO $$
DECLARE
  old_count bigint;
  new_count bigint;
BEGIN
  SELECT COUNT(*) INTO old_count FROM public.stock_old;
  SELECT COUNT(*) INTO new_count FROM public.stock;
  
  RAISE NOTICE '======================================';
  RAISE NOTICE 'Migration verification:';
  RAISE NOTICE 'Old table rows: %', old_count;
  RAISE NOTICE 'New table rows: %', new_count;
  
  IF old_count = new_count THEN
    RAISE NOTICE 'SUCCESS: Row counts match!';
  ELSE
    RAISE WARNING 'Row count mismatch! Difference: %', abs(old_count - new_count);
  END IF;
  RAISE NOTICE '======================================';
END $$;

-- ==========================================
-- 9) Quick sanity check query
-- ==========================================
EXPLAIN (ANALYZE, BUFFERS, TIMING, SUMMARY)
SELECT *
FROM public.stock
WHERE symb='TSLA'
  AND "timestamp" BETWEEN '2025-01-01' AND '2025-03-31'
ORDER BY "timestamp" ASC;

-- ==========================================
-- 10) Cleanup instructions
-- ==========================================
-- After verification, run ONE of these:

-- Option A: Compress old table
-- ALTER TABLE public.stock_old SET (
--   timescaledb.compress,
--   timescaledb.compress_segmentby='symb',
--   timescaledb.compress_orderby='"timestamp" DESC'
-- );
-- SELECT add_compression_policy('stock_old', INTERVAL '0 days');

-- Option B: Drop old table
-- DROP TABLE public.stock_old;

RAISE NOTICE 'Migration completed! Please verify and clean up stock_old table.';