import subprocess,json
sql=r"""BEGIN READ ONLY; SET LOCAL statement_timeout='240s'; SET LOCAL lock_timeout='3s';
WITH metrics AS (
 SELECT m.metric_code,count(*) AS facts,count(DISTINCT f.company_id) AS companies,min(f.period_end) AS earliest,max(f.period_end) AS latest
 FROM public.financial_fact f LEFT JOIN public.financial_metric m ON m.id=f.metric_id GROUP BY m.metric_code
)
SELECT json_build_object('physicalLocalFacts',(SELECT count(*) FROM source_local.financial_fact),'physicalRemoteFacts',(SELECT count(*) FROM source_remote.financial_fact),'integratedFacts',(SELECT sum(facts) FROM metrics),'metrics',(SELECT json_agg(metrics ORDER BY metric_code) FROM metrics),'integratedCompanies',(SELECT count(*) FROM public.company),'integratedFilings',(SELECT count(*) FROM public.filing),'servingMappings',(SELECT count(*) FROM public.financial_metric_mapping),'reviewedMappingOverlay',(SELECT count(*) FROM finance_review665.metric_mapping));
COMMIT;"""
r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=sql,text=True,capture_output=True,timeout=260)
assert r.returncode==0,'FINANCIAL_COUNTS_READ_FAILED'
print(r.stdout)
