import subprocess,json
from pathlib import Path
root=Path('/opt/trader-runtime/account657');before=json.loads((root/'prepared.json').read_text())
def count(t):
 r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input='SELECT count(*) FROM '+t+';',capture_output=True,text=True)
 assert r.returncode==0,'AUDIT_READ_FAILED'
 return int(r.stdout)
after={t:count(t) for t in before['targets']};assert all(n==0 for n in after.values()),'PRIVATE_ROWS_REMAIN'
protected={t:count(t) for t in before['protectedCounts']}
assert protected==before['protectedCounts'],'PROTECTED_COUNT_DRIFT'
result={'status':'VERIFIED','emptyTables':after,'protectedTables':len(protected),'protectedCounts':protected,'protectedCountsUnchanged':True}
(root/'database-audit.json').write_text(json.dumps(result));print(json.dumps(result))
