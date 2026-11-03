import json,subprocess,ssl,urllib.request,base64
from pathlib import Path
def sql(s):
 r=subprocess.run(['docker','exec','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated','-c',s],capture_output=True,text=True)
 assert r.returncode==0,'FINAL_READ_FAILED';return json.loads(r.stdout)
x=sql("SELECT json_build_object('users',(SELECT count(*) FROM application.users),'admins',(SELECT count(*) FROM application.users WHERE role=0),'ownerFingerprint',(SELECT md5(string_agg(row_to_json(u)::text,',' ORDER BY id)) FROM application.users u),'notes',(SELECT count(*) FROM application.note),'teams',(SELECT count(*) FROM application.team),'pages',(SELECT count(*) FROM application.page),'nodes',(SELECT count(*) FROM application.node),'edges',(SELECT count(*) FROM application.edge),'consents',(SELECT count(*) FROM application.policy_consent),'uploadParts',(SELECT count(*) FROM application.note_upload_part),'unfinishedIndexJobs',(SELECT count(*) FROM ai.index_job WHERE status IN ('RUNNING','PENDING','RETRY_WAIT')),'prepared',(SELECT count(*) FROM pg_prepared_xacts),'idleTransactions',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction')); ")
assert x['users']==x['admins']==1 and all(x[k]==0 for k in ['notes','teams','pages','nodes','edges','uploadParts','unfinishedIndexJobs','prepared','idleTransactions']),'POST_TEST_ROWS_REVIEW'
before=json.loads(Path('/opt/trader-runtime/account657/prepared.json').read_text())['protectedCounts']
protected={t:sql('SELECT count(*) FROM '+t) for t in before if t.split('.')[0] in ['source_local','source_remote','price_incremental567','price_refresh559','price_gap581','integration_meta']}
assert all(v==before[k] for k,v in protected.items()),'FINANCIAL_COUNTS_CHANGED'
p=Path('/data/trader-integrated547/opensearch');auth=json.loads((p/'search-credentials.json').read_text());ctx=ssl.create_default_context(cafile=str(p/'authority/ca.pem'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx));req=urllib.request.Request('https://10.0.2.155:9200/trader-chunks-v1/_count')
req.add_header('Authorization','Basic '+base64.b64encode((auth['username']+':'+auth['password']).encode()).decode())
with opener.open(req,timeout=30) as r:chunks=json.load(r)['count']
assert chunks==0,'SEARCH_FIXTURE_CHUNKS_REMAIN'
print(json.dumps({**x,'protectedFinancialTables':len(protected),'protectedCountsUnchanged':True,'searchChunks':chunks,'protectedCounts':protected}))
