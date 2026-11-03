-- ==========================================
-- Continue migration from index creation step
-- Run this if data is already in stock_v2_90d
-- ==========================================

\timing on

-- ==========================================
-- 1) Recreate indexes (skip if exists)
-- ==========================================
DO $$
DECLARE 
  rec RECORD; 
  def TEXT; 
  idx_count int := 0; 
  skip_count int := 0;
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
END $$;

-- ==========================================
-- 2) Recreate constraints (skip if exists)
-- ==========================================
DO $$
DECLARE 
  r RECORD; 
  ddl TEXT; 
  con_count int := 0; 
  skip_count int := 0;
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
END $$;

-- ==========================================
-- 3) Analyze table
-- ==========================================
ANALYZE public.stock_v2_90d;

-- ==========================================
-- 4) Atomic swap + inbound FK rewire
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

  -- Drop inbound FKs
  DO $$
  DECLARE 
    r RECORD; 
    fk_count int := 0;
  BEGIN
    FOR r IN SELECT * FROM _inbound_fk LOOP
      EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I;', r.child_table, r.fk_name);
      fk_count := fk_count + 1;
    END LOOP;
    RAISE NOTICE 'Dropped % foreign keys', fk_count;
  END $$;

  -- Rename tables
  ALTER TABLE public.stock        RENAME TO stock_old;
  ALTER TABLE public.stock_v2_90d RENAME TO stock;
  RAISE NOTICE 'Tables renamed successfully';

  -- Recreate inbound FKs
  DO $$
  DECLARE 
    r RECORD; 
    fk_count int := 0;
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
-- 5) Verify migration
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
-- 6) Quick sanity check query
-- ==========================================
EXPLAIN (ANALYZE, BUFFERS, TIMING, SUMMARY)
SELECT *
FROM public.stock
WHERE symb='TSLA'
  AND "timestamp" BETWEEN '2025-01-01' AND '2025-03-31'
ORDER BY "timestamp" ASC;

-- ==========================================
-- 7) Cleanup instructions
-- ==========================================
RAISE NOTICE 'Migration completed! You can now:';
RAISE NOTICE '1. Verify data integrity';
RAISE NOTICE '2. Drop old table: DROP TABLE public.stock_old;';
RAISE NOTICE '3. Or compress it for backup';