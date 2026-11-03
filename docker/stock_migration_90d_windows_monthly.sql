-- =========================================================
--  Migrate public.stock (30d) → 90d by monthly batches (Windows-friendly)
--  - No psql variables, no \gset/\gexec (works on Windows CMD/PowerShell)
--  - Monthly batched INSERTs via PROCEDURE (each month COMMIT)
--  - Build indexes/constraints AFTER bulk load (faster)
--  - Atomic swap (LOCK+RENAME) + inbound FK rewire
-- =========================================================

\timing on

-- =========================
-- 0) Preflight checks
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

-- Dependent view/materialized view check (abort if exists)
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
-- 1) Prepare destination hypertable (90 days)
--    (no indexes/constraints yet for speed)
-- ==========================================
DO $$
BEGIN
  EXECUTE 'DROP TABLE IF EXISTS public.stock_v2_90d CASCADE';
  EXECUTE '
    CREATE TABLE public.stock_v2_90d
    (LIKE public.stock
     INCLUDING DEFAULTS
     INCLUDING IDENTITY
     INCLUDING GENERATED
     INCLUDING STORAGE
     INCLUDING COMMENTS
    )';
END $$;

-- time dimension: 90 days, space dimension: symb with 8 partitions
SELECT create_hypertable('public.stock_v2_90d', 'timestamp', chunk_time_interval => INTERVAL '90 days');
SELECT add_dimension('public.stock_v2_90d', 'symb', number_partitions => 8);

-- ==========================================
-- 2) Bulk load by monthly batches (each month COMMIT)
--    Use PROCEDURE so we can COMMIT per month (avoids max_locks blow-up)
-- ==========================================
-- Speed knobs (session-local)
SET synchronous_commit   = off;
SET maintenance_work_mem = '2047MB';  -- max allowed
SET work_mem             = '256MB';

DROP PROCEDURE IF EXISTS public.migrate_stock_monthly();
CREATE PROCEDURE public.migrate_stock_monthly()
LANGUAGE plpgsql
AS $$
DECLARE
  tmin timestamptz;
  tmax timestamptz;
  m_start timestamptz;
  m_end   timestamptz;
BEGIN
  SELECT date_trunc('month', MIN("timestamp")),
         date_trunc('month', MAX("timestamp"))
    INTO tmin, tmax
  FROM public.stock;

  IF tmin IS NULL OR tmax IS NULL THEN
    RAISE EXCEPTION 'public.stock is empty';
  END IF;

  m_start := tmin;
  WHILE m_start <= tmax LOOP
    m_end := m_start + INTERVAL '1 month';
    RAISE NOTICE 'Inserting month: % to %', m_start, m_end;

    INSERT INTO public.stock_v2_90d
    SELECT *
    FROM public.stock
    WHERE "timestamp" >= m_start
      AND "timestamp"  < m_end;

    -- commit this month to avoid lock/memory accumulation
    COMMIT;
    -- start a fresh transaction for the next month
    START TRANSACTION;

    m_start := m_end;
  END LOOP;
END
$$;

-- Important: CALL must be executed in top-level (autocommit) context.
\set AUTOCOMMIT on
CALL public.migrate_stock_monthly();

-- ==========================================
-- 3) Recreate indexes and constraints AFTER load
-- ==========================================
-- 3.1 Indexes (copy definitions; create on destination)
DO $$
DECLARE rec RECORD; def TEXT;
BEGIN
  FOR rec IN
    SELECT schemaname, tablename, indexname
    FROM pg_indexes
    WHERE schemaname='public' AND tablename='stock'
  LOOP
    SELECT pg_get_indexdef(i.indexrelid) INTO def
    FROM pg_class t
    JOIN pg_index i ON i.indrelid = t.oid
    JOIN pg_class x ON x.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname='public'
      AND t.relname='stock'
      AND x.relname=rec.indexname;

    -- switch target table
    def := replace(def, ' ON public.stock ', ' ON public.stock_v2_90d ');

    -- create normally (faster than CONCURRENTLY during planned downtime)
    EXECUTE def;
  END LOOP;
END $$;

-- 3.2 Constraints: primary/unique/check
DO $$
DECLARE r RECORD; ddl TEXT;
BEGIN
  FOR r IN
    SELECT conname, contype, pg_get_constraintdef(oid) AS defn
    FROM pg_constraint
    WHERE conrelid = 'public.stock'::regclass
      AND contype IN ('p','u','c')
  LOOP
    ddl := format('ALTER TABLE public.stock_v2_90d ADD CONSTRAINT %I %s;', r.conname, r.defn);
    EXECUTE ddl;
  END LOOP;
END $$;

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
  LOCK TABLE public.stock        IN ACCESS EXCLUSIVE MODE;
  LOCK TABLE public.stock_v2_90d IN ACCESS EXCLUSIVE MODE;

  -- Drop inbound FKs that point to public.stock
  DO $$
  DECLARE r RECORD;
  BEGIN
    FOR r IN SELECT * FROM _inbound_fk LOOP
      EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I;', r.child_table, r.fk_name);
    END LOOP;
  END $$;

  -- Rename tables: stock -> stock_old, stock_v2_90d -> stock
  ALTER TABLE public.stock        RENAME TO stock_old;
  ALTER TABLE public.stock_v2_90d RENAME TO stock;

  -- Recreate inbound FKs with original definitions
  -- (fk_def contains "REFERENCES public.stock" which now points to the NEW table)
  DO $$
  DECLARE r RECORD;
  BEGIN
    FOR r IN SELECT * FROM _inbound_fk LOOP
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s;', r.child_table, r.fk_name, r.fk_def);
    END LOOP;
  END $$;

COMMIT;

-- ==========================================
-- 5) Quick sanity check
-- ==========================================
EXPLAIN (ANALYZE, BUFFERS, TIMING, SUMMARY)
SELECT *
FROM public.stock
WHERE symb='TSLA'
  AND "timestamp" BETWEEN '2025-01-01' AND '2025-03-31'
ORDER BY "timestamp" ASC;

-- (optional) keep or compress old table
-- ALTER TABLE public.stock_old
--   SET (timescaledb.compress,
--        timescaledb.compress_segmentby='symb',
--        timescaledb.compress_orderby='"timestamp" DESC');
-- SELECT add_compression_policy('stock_old', INTERVAL '0 days');

-- (optional) drop old table after validation
-- DROP TABLE public.stock_old;

-- Done.
