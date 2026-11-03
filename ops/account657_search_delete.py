import json,ssl,urllib.request,base64
from pathlib import Path
p=Path('/data/trader-integrated547/opensearch');root=Path('/opt/trader-runtime/account657')
assert json.loads((root/'database-complete.json').read_text())['committed']
auth=json.loads((p/'search-credentials.json').read_text());ctx=ssl.create_default_context(cafile=str(p/'authority/ca.pem'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
header={'Authorization':'Basic '+base64.b64encode((auth['username']+':'+auth['password']).encode()).decode(),'Content-Type':'application/json'}
def request(path,body=None):
 req=urllib.request.Request('https://10.0.2.155:9200'+path,data=json.dumps(body).encode() if body is not None else None,headers=header)
 with opener.open(req,timeout=120) as r:return json.load(r)
index='trader-chunks-v1'
before=request('/'+index+'/_search',{'size':0,'aggs':{'types':{'terms':{'field':'sourceType','size':20}}}})
types=before['aggregations']['types']['buckets'];assert all(t['key'] in ['NOTE','NODE','EDGE'] for t in types),'UNKNOWN_SEARCH_TYPE'
total=before['hits']['total']['value'];assert sum(t['doc_count'] for t in types)==total,'MISSING_SOURCE_TYPE'
deleted=request('/'+index+'/_delete_by_query?refresh=true&conflicts=abort',{'query':{'terms':{'sourceType':['NOTE','NODE','EDGE']}}})
assert not deleted.get('failures') and not deleted.get('version_conflicts') and deleted['deleted']==total,'SEARCH_DELETE_INCOMPLETE'
after=request('/'+index+'/_count');assert after['count']==0,'SEARCH_REMAINS'
result={'index':index,'deleted':total,'remaining':0,'mappingPreserved':True,'sourceTypes':types}
(root/'search-complete.json').write_text(json.dumps(result));print(json.dumps(result))
