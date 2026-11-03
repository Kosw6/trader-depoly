import subprocess,json
from pathlib import Path
root=Path('/opt/trader-runtime/account657');before=json.loads((root/'prepared.json').read_text())
assert not (root/'database-complete.json').exists(),'ALREADY_COMPLETED'
targets=before['targets'];assert len(targets)==38 and 'application.users' in targets
allowed_schemas={'application','ai','control649'}
assert all(t.split('.')[0] in allowed_schemas and all(c.isalnum() or c in '._' for c in t) for t in targets)
checks=''
for t,n in before['before'].items():checks+=f"IF (SELECT count(*) FROM {t}) <> {n} THEN RAISE EXCEPTION 'TARGET_DRIFT'; END IF;\n"
sql="BEGIN; SET LOCAL lock_timeout='10s'; SET LOCAL statement_timeout='180s';\nLOCK TABLE "+','.join(targets)+" IN ACCESS EXCLUSIVE MODE;\nDO $$ BEGIN "+checks+" END $$;\nTRUNCATE TABLE "+','.join(targets)+" CONTINUE IDENTITY RESTRICT;\nDO $$ BEGIN "+''.join(f"IF EXISTS(SELECT 1 FROM {t}) THEN RAISE EXCEPTION 'NOT_EMPTY'; END IF;" for t in targets)+" END $$;\nCOMMIT;\nSELECT json_build_object('committed',true,'tables',38);"
r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=sql,capture_output=True,text=True)
assert r.returncode==0,'DELETE_TRANSACTION_FAILED_NO_REPLAY'
result=json.loads(r.stdout);result.update({'before':before['before'],'identityReset':False,'cascade':False})
(root/'database-complete.json').write_text(json.dumps(result))
print(json.dumps(result))
