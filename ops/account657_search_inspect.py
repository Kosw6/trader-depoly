import json,ssl,urllib.request,base64
from pathlib import Path
p=Path('/data/trader-integrated547/opensearch')
auth=json.loads((p/'search-credentials.json').read_text())
ctx=ssl.create_default_context(cafile=str(p/'authority/ca.pem'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
req=urllib.request.Request('https://10.0.2.155:9200/_cat/indices?format=json&h=index,docs.count')
req.add_header('Authorization','Basic '+base64.b64encode((auth['username']+':'+auth['password']).encode()).decode())
import urllib.error,subprocess
try:
 with opener.open(req,timeout=30) as r:rows=json.load(r)
 result={'indices':rows}
except urllib.error.HTTPError as e:
 result={'status':e.code}
 x=json.loads(subprocess.check_output(['docker','inspect','trader-opensearch']))[0]
 result['envNames']=[v.split('=',1)[0] for v in x['Config']['Env']]
 req=urllib.request.Request('https://10.0.2.155:9200/trader-chunks-v1/_count',headers={'Authorization':req.get_header('Authorization')})
 with opener.open(req,timeout=30) as r:result['chunks']=json.load(r)
print(json.dumps(result))
