BEGIN;
SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s';
DO $$ BEGIN PERFORM pg_advisory_xact_lock(6670001); IF position('finance_review665' in pg_get_viewdef('public.financial_metric_mapping'::regclass))=0 THEN RAISE EXCEPTION 'UNEXPECTED_MAPPING_VIEW'; END IF; END $$;
CREATE SCHEMA finance_mapping667;
CREATE TABLE finance_mapping667.approved(
 id bigint GENERATED ALWAYS AS IDENTITY(START WITH 3000000000000) PRIMARY KEY,
 company_id bigint NOT NULL,metric_id bigint NOT NULL,taxonomy varchar(50) NOT NULL CHECK(taxonomy='us-gaap'),source_tag varchar(255) NOT NULL,
 priority integer NOT NULL DEFAULT 100,valid_from date NOT NULL,valid_to date NOT NULL,
 policy_version text NOT NULL,proof jsonb NOT NULL,proof_hash char(64) NOT NULL,
 active boolean NOT NULL DEFAULT TRUE,created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(valid_from=valid_to),UNIQUE(company_id,metric_id,valid_from,valid_to));
CREATE TABLE finance_mapping667.held(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 company_id bigint NOT NULL,metric_id bigint NOT NULL,period_end date NOT NULL,reason text NOT NULL,
 proof_hash char(64) NOT NULL,proof jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(company_id,metric_id,period_end,reason,proof_hash));
CREATE TABLE finance_mapping667.receipt(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 company_id bigint NOT NULL,policy_version text NOT NULL,start_date date NOT NULL,end_date date NOT NULL,
 summary jsonb NOT NULL,input_hash char(64) NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE finance_mapping667.queue(company_id bigint PRIMARY KEY,status text NOT NULL CHECK(status IN ('PENDING','DONE','HELD')),
 reason text NOT NULL,requested_at timestamptz NOT NULL DEFAULT now(),generation bigint NOT NULL DEFAULT 1,
 start_date date NOT NULL DEFAULT '1900-01-01',end_date date,annual_only boolean NOT NULL DEFAULT FALSE,
 processed_at timestamptz,receipt_id bigint REFERENCES finance_mapping667.receipt(id));
CREATE INDEX queue667_pending ON finance_mapping667.queue(requested_at,company_id) WHERE status='PENDING';
CREATE INDEX approved667_metric_date ON finance_mapping667.approved(metric_id,valid_from,valid_to) WHERE active;
DO $$ DECLARE old text; BEGIN
 old:=rtrim(trim(pg_get_viewdef('public.financial_metric_mapping'::regclass)),';');
 EXECUTE 'CREATE OR REPLACE VIEW public.financial_metric_mapping AS '||old||' UNION ALL SELECT id,taxonomy,source_tag,metric_id,company_id,priority,valid_from,valid_to FROM finance_mapping667.approved WHERE active';
END $$;
GRANT USAGE ON SCHEMA finance_mapping667 TO trader_control649;
GRANT SELECT,INSERT,UPDATE ON finance_mapping667.approved,finance_mapping667.queue TO trader_control649;
GRANT SELECT,INSERT ON finance_mapping667.held,finance_mapping667.receipt TO trader_control649;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA finance_mapping667 TO trader_control649;
GRANT SELECT ON public.company,public.financial_metric,public.financial_fact,public.filing,public.financial_metric_mapping TO trader_control649;
COMMIT;
SELECT json_build_object('schema','finance_mapping667','sourceTablesModified',false,'newApprovals',(SELECT count(*) FROM finance_mapping667.approved));
