BEGIN;
SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s';
ALTER TABLE finance_mapping667.queue ADD COLUMN refresh_requested boolean NOT NULL DEFAULT false;
ALTER TABLE finance_mapping667.receipt ADD COLUMN queue_generation bigint;
CREATE UNIQUE INDEX receipt668_generation ON finance_mapping667.receipt(company_id,queue_generation) WHERE queue_generation IS NOT NULL;
GRANT UPDATE(queue_generation) ON finance_mapping667.receipt TO trader_control649;
CREATE SCHEMA finance_mapping_ops668;
CREATE TABLE finance_mapping_ops668.schedule(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,name varchar(100) NOT NULL,cron_expression text NOT NULL,
 timezone text NOT NULL,parameters jsonb NOT NULL,enabled boolean NOT NULL DEFAULT false,
 next_run_at timestamptz,last_run_at timestamptz,last_status text,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE finance_mapping_ops668.run(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,request_key varchar(100) UNIQUE NOT NULL,
 parameters jsonb NOT NULL,requested_by varchar(100) NOT NULL,
 schedule_id bigint REFERENCES finance_mapping_ops668.schedule(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE finance_mapping_ops668.run_item(
 run_id bigint NOT NULL REFERENCES finance_mapping_ops668.run(id),company_id bigint NOT NULL,
 generation bigint NOT NULL,PRIMARY KEY(run_id,company_id));
CREATE INDEX run668_recent ON finance_mapping_ops668.run(id DESC);
-- Controller and worker share the existing limited control role.
GRANT USAGE ON SCHEMA finance_mapping_ops668 TO trader_control649;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA finance_mapping_ops668 TO trader_control649;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA finance_mapping_ops668 TO trader_control649;
COMMIT;
