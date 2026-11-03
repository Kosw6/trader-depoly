ROWS=[{'value': '6910000000.0000000000', 'period_start': '2016-02-01', 'period_end': '2017-01-29', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2017, 'fiscal_period': 'FY', 'report_date': '2017-01-29', 'filing_date': '2017-03-01', 'accession_number': '0001045810-17-000027', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581017000027/nvda-2017x10k.htm', 'form_type': '10-K'}, {'value': '9714000000.0000000000', 'period_start': '2017-01-30', 'period_end': '2018-01-28', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2018, 'fiscal_period': 'FY', 'report_date': '2018-01-28', 'filing_date': '2018-02-28', 'accession_number': '0001045810-18-000010', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581018000010/nvda-2018x10k.htm', 'form_type': '10-K'}, {'value': '11716000000.0000000000', 'period_start': '2018-01-29', 'period_end': '2019-01-27', 'source_tag': 'RevenueFromContractWithCustomerExcludingAssessedTax', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2019, 'fiscal_period': 'FY', 'report_date': '2019-01-27', 'filing_date': '2019-02-21', 'accession_number': '0001045810-19-000023', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581019000023/nvda-2019x10k.htm', 'form_type': '10-K'}, {'value': '10918000000.0000000000', 'period_start': '2019-01-28', 'period_end': '2020-01-26', 'source_tag': 'RevenueFromContractWithCustomerExcludingAssessedTax', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2020, 'fiscal_period': 'FY', 'report_date': '2020-01-26', 'filing_date': '2020-02-20', 'accession_number': '0001045810-20-000010', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581020000010/nvda-2020x10k.htm', 'form_type': '10-K'}, {'value': '16675000000.0000000000', 'period_start': '2020-01-27', 'period_end': '2021-01-31', 'source_tag': 'RevenueFromContractWithCustomerExcludingAssessedTax', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2021, 'fiscal_period': 'FY', 'report_date': '2021-01-31', 'filing_date': '2021-02-26', 'accession_number': '0001045810-21-000010', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581021000010/nvda-20210131.htm', 'form_type': '10-K'}, {'value': '26914000000.0000000000', 'period_start': '2021-02-01', 'period_end': '2022-01-30', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2022, 'fiscal_period': 'FY', 'report_date': '2022-01-30', 'filing_date': '2022-03-18', 'accession_number': '0001045810-22-000036', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581022000036/nvda-20220130.htm', 'form_type': '10-K'}, {'value': '26974000000.0000000000', 'period_start': '2022-01-31', 'period_end': '2023-01-29', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2023, 'fiscal_period': 'FY', 'report_date': '2023-01-29', 'filing_date': '2023-02-24', 'accession_number': '0001045810-23-000017', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581023000017/nvda-20230129.htm', 'form_type': '10-K'}, {'value': '60922000000.0000000000', 'period_start': '2023-01-30', 'period_end': '2024-01-28', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2024, 'fiscal_period': 'FY', 'report_date': '2024-01-28', 'filing_date': '2024-02-21', 'accession_number': '0001045810-24-000029', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm', 'form_type': '10-K'}, {'value': '130497000000.0000000000', 'period_start': '2024-01-29', 'period_end': '2025-01-26', 'source_tag': 'Revenues', 'taxonomy': 'us-gaap', 'unit': 'USD', 'fiscal_year': 2025, 'fiscal_period': 'FY', 'report_date': '2025-01-26', 'filing_date': '2025-02-26', 'accession_number': '0001045810-25-000023', 'document_url': 'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm', 'form_type': '10-K'}]
EXPECTED_VIEW_MD5='04cb594cf3ca7796644b9e4031c91680'

import subprocess,json,hashlib
from pathlib import Path
root=Path('/opt/trader-runtime/releases/665-mapping-v2');root.mkdir(mode=0o700,parents=True,exist_ok=False)
payload=json.dumps(ROWS);assert '$review665$' not in payload
sql=r"""BEGIN;
SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s';
DO $$ BEGIN PERFORM pg_advisory_xact_lock(6650001); END $$;
CREATE TEMP TABLE proposal AS SELECT * FROM jsonb_to_recordset($review665$"""+payload+r"""$review665$::jsonb)
AS x(value numeric,period_start date,period_end date,source_tag text,taxonomy text,unit text,fiscal_year int,fiscal_period text,report_date date,filing_date date,accession_number text,document_url text,form_type text);
DO $$ BEGIN
 IF md5(pg_get_viewdef('public.financial_metric_mapping'::regclass)) <> '"""+EXPECTED_VIEW_MD5+r"""' THEN RAISE EXCEPTION 'VIEW_CHANGED'; END IF;
 IF (SELECT count(*) FROM proposal)<>9 OR EXISTS(SELECT 1 FROM proposal p WHERE NOT EXISTS (
 SELECT 1 FROM public.financial_fact f JOIN public.financial_metric m ON m.id=f.metric_id JOIN public.filing g ON g.id=f.filing_id AND g.company_id=f.company_id
 WHERE f.company_id=1440 AND m.metric_code='REVENUE' AND f.value=p.value AND f.period_start=p.period_start AND f.period_end=p.period_end AND f.source_tag=p.source_tag AND f.taxonomy='us-gaap' AND f.unit='USD' AND (f.dimensions IS NULL OR f.dimensions='{}'::jsonb)
 AND g.accession_number=p.accession_number AND g.report_date=p.period_end AND g.document_url=p.document_url)) THEN RAISE EXCEPTION 'SOURCE_PROOF_CHANGED'; END IF;
END $$;
CREATE TEMP TABLE preserved AS SELECT (SELECT count(*) FROM source_local.financial_metric_mapping) AS local_maps,(SELECT count(*) FROM source_remote.financial_metric_mapping) AS remote_maps,(SELECT count(*) FROM public.financial_fact f JOIN public.financial_metric m ON m.id=f.metric_id WHERE f.company_id=1440 AND m.metric_code='REVENUE') AS facts;
CREATE SCHEMA finance_review665;
CREATE TABLE finance_review665.metric_mapping(
 id bigint PRIMARY KEY, taxonomy varchar(50) NOT NULL, source_tag varchar(255) NOT NULL,
 metric_id bigint NOT NULL,company_id bigint NOT NULL CHECK(company_id=1440),priority integer NOT NULL,
 valid_from date NOT NULL,valid_to date NOT NULL,approved boolean NOT NULL CHECK(approved),
 proof jsonb NOT NULL,reviewed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(company_id,metric_id,valid_from,valid_to));
INSERT INTO finance_review665.metric_mapping(id,taxonomy,source_tag,metric_id,company_id,priority,valid_from,valid_to,approved,proof)
SELECT 2000000000000+p.fiscal_year,p.taxonomy,p.source_tag,m.id,1440,100,p.period_end,p.period_end,TRUE,to_jsonb(p)
FROM proposal p CROSS JOIN public.financial_metric m WHERE m.metric_code='REVENUE';
DO $$ DECLARE old text; BEGIN
 old:=rtrim(trim(pg_get_viewdef('public.financial_metric_mapping'::regclass)),';');
 EXECUTE 'CREATE OR REPLACE VIEW public.financial_metric_mapping AS '||old||' UNION ALL SELECT id,taxonomy,source_tag,metric_id,company_id,priority,valid_from,valid_to FROM finance_review665.metric_mapping WHERE approved';
 IF (SELECT count(*) FROM finance_review665.metric_mapping)<>9 THEN RAISE EXCEPTION 'MAPPING_COUNT'; END IF;
 IF EXISTS(SELECT 1 FROM preserved WHERE local_maps<>(SELECT count(*) FROM source_local.financial_metric_mapping) OR remote_maps<>(SELECT count(*) FROM source_remote.financial_metric_mapping) OR facts<>(SELECT count(*) FROM public.financial_fact f JOIN public.financial_metric m ON m.id=f.metric_id WHERE f.company_id=1440 AND m.metric_code='REVENUE')) THEN RAISE EXCEPTION 'ORIGINAL_CHANGED'; END IF;
END $$;
COMMIT;
SELECT json_build_object('reviewedMappings',count(*),'onlyCompany',min(company_id),'originalFactsAndMappingsPreserved',true,'proofsStored',bool_and(proof IS NOT NULL)) FROM finance_review665.metric_mapping;
"""
(root/'applied.sql').write_text(sql);(root/'applied.sql').chmod(0o600)
r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=sql,text=True,capture_output=True,timeout=90)
assert r.returncode==0,'REVIEWED_MAPPING_TRANSACTION_FAILED'
print(r.stdout)
