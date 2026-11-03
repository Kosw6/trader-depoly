import subprocess,json
sql=r"""BEGIN READ ONLY; SET LOCAL statement_timeout='240s'; SET LOCAL lock_timeout='3s'; SET LOCAL temp_file_limit='1GB'; SET LOCAL work_mem='16MB';
WITH wanted AS MATERIALIZED(SELECT DISTINCT company_id FROM public.asset WHERE upper(ticker) IN ('NVDA','AAPL','MSFT','AMZN','GOOGL','META','TSLA','AMD','AVGO','INTC') AND active AND company_id IS NOT NULL), policy(code,unit,tags) AS (VALUES
 ('REVENUE','USD',ARRAY['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax']),
 ('NET_INCOME','USD',ARRAY['NetIncomeLoss']),('OPERATING_INCOME','USD',ARRAY['OperatingIncomeLoss']),
 ('ASSETS','USD',ARRAY['Assets']),('LIABILITIES','USD',ARRAY['Liabilities']),('DILUTED_EPS','USD/shares',ARRAY['EarningsPerShareDiluted'])),
k AS MATERIALIZED (
 SELECT f.company_id,f.metric_id,m.metric_code,f.period_end,array_agg(DISTINCT 'us-gaap:'||f.source_tag) AS fact_tags
 FROM public.financial_fact f JOIN public.financial_metric m ON m.id=f.metric_id JOIN policy p ON p.code=m.metric_code
 WHERE f.company_id IN (SELECT company_id FROM wanted) AND f.taxonomy='us-gaap' AND f.unit=p.unit AND f.source_tag=ANY(p.tags)
 AND (f.dimensions IS NULL OR f.dimensions='{}'::jsonb) AND f.filing_id IS NOT NULL AND f.period_end<=CURRENT_DATE
 GROUP BY f.company_id,f.metric_id,m.metric_code,f.period_end),
 maps AS MATERIALIZED(SELECT * FROM public.financial_metric_mapping),
 specific AS (
 SELECT k.company_id,k.metric_id,k.period_end,array_agg(DISTINCT x.taxonomy||':'||x.source_tag) AS tags
 FROM k JOIN maps x ON x.company_id=k.company_id AND x.metric_id=k.metric_id
 AND (x.valid_from IS NULL OR x.valid_from<=k.period_end) AND (x.valid_to IS NULL OR x.valid_to>=k.period_end)
 GROUP BY k.company_id,k.metric_id,k.period_end),
 generic AS (
 SELECT k.company_id,k.metric_id,k.period_end,array_agg(DISTINCT x.taxonomy||':'||x.source_tag) AS tags
 FROM k JOIN maps x ON x.company_id IS NULL AND x.metric_id=k.metric_id
 AND (x.valid_from IS NULL OR x.valid_from<=k.period_end) AND (x.valid_to IS NULL OR x.valid_to>=k.period_end)
 GROUP BY k.company_id,k.metric_id,k.period_end),
 classified AS MATERIALIZED (
 SELECT k.*,CASE WHEN coalesce(s.tags,g.tags) IS NULL THEN 'MAPPING_MISSING'
 WHEN cardinality(coalesce(s.tags,g.tags))<>1 THEN 'MAPPING_CONFLICT'
 WHEN NOT ((coalesce(s.tags,g.tags))[1]=ANY(k.fact_tags)) THEN 'MAPPED_TAG_NOT_IN_FACTS'
 ELSE 'COVERED' END AS coverage
 FROM k LEFT JOIN specific s USING(company_id,metric_id,period_end) LEFT JOIN generic g USING(company_id,metric_id,period_end)),
 grouped AS (SELECT metric_code,coverage,count(*) AS company_metric_end_keys,count(DISTINCT company_id) AS companies,min(period_end) AS earliest,max(period_end) AS latest FROM classified GROUP BY metric_code,coverage),
 samples AS (SELECT c.company_name AS name,x.company_id,x.metric_code,x.coverage,count(*) AS affected_periods,min(x.period_end) AS earliest,max(x.period_end) AS latest FROM classified x JOIN public.company c ON c.id=x.company_id WHERE x.coverage<>'COVERED' GROUP BY c.company_name,x.company_id,x.metric_code,x.coverage ORDER BY affected_periods DESC,c.company_name LIMIT 15)
SELECT json_build_object('basis','Sample: ten named US tickers, supported six metrics; company/metric/report-end candidate keys, not full source-quality approval','coverage',(SELECT json_agg(grouped ORDER BY metric_code,coverage) FROM grouped),'sampleCompanies',(SELECT json_agg(samples) FROM samples));
COMMIT;"""
r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=sql,text=True,capture_output=True,timeout=260)
if r.returncode==0:print(r.stdout)
else:print(json.dumps({'status':'FAILED','safeError':next((x for x in r.stderr.splitlines() if 'ERROR:' in x),'READ_FAILED')}))
