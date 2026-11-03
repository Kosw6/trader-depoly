"""Private-host MVCC operational backup + real restore. Never full price history."""
import hashlib,json,os,re,shutil,subprocess,time,sys
from pathlib import Path

CONTAINER='trader-integrated547-db';DB='trader_integrated'
BASE=['docker','exec',CONTAINER]
def sql(db,query):
 r=subprocess.run(BASE+['psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',db,'-c',query],capture_output=True,text=True,timeout=120)
 assert r.returncode==0,'BACKUP_SQL_FAILED'
 return r.stdout.strip()
def run(args):
 r=subprocess.run(BASE+args,capture_output=True,timeout=300)
 assert r.returncode==0,'BACKUP_'+args[0].replace('-','_').upper()+'_FAILED'
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def stage(generation):
 assert re.fullmatch(r'\d{8}T\d{6}Z-[a-z0-9]{6}',generation),'INVALID_BACKUP_GENERATION'
 os.umask(0o077)
 mount=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]['Mounts']
 volume=next(m for m in mount if m['Destination']=='/var/lib/postgresql/data')
 host=Path(volume['Source']);relative='operational649/'+generation
 work=host/relative;assert not work.exists(),'BACKUP_EXISTS_INSPECT_RECEIPT'
 work.mkdir(parents=True,mode=0o700)
 for directory in [work.parent,work]:
  os.chmod(directory,0o700);os.chown(directory,host.stat().st_uid,host.stat().st_gid)
 inside='/var/lib/postgresql/data/'+relative
 assert sql(DB,'SELECT count(*) FROM pg_foreign_server')=='0','SCHEMA_HAS_EXTERNAL_CONNECTIONS'
 # Derived historical price-quality issues reference all remote price history.
 # Preserve these on original EBS/recovery snapshots, not in a daily operational copy.
 roots="n.nspname IN ('application','ai','control649','finance_review665','finance_mapping667','finance_mapping_ops668') AND c.relkind='r' AND c.relname NOT IN ('admin_session','price_bar_quality_issue')"
 query="WITH RECURSIVE chosen(oid) AS (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+roots+" UNION SELECT f.confrelid FROM pg_constraint f JOIN chosen s ON s.oid=f.conrelid WHERE f.contype='f') SELECT json_agg(json_build_object('schema',n.nspname,'table',c.relname,'bytes',pg_total_relation_size(c.oid)) ORDER BY n.nspname,c.relname) FROM chosen s JOIN pg_class c ON c.oid=s.oid JOIN pg_namespace n ON n.oid=c.relnamespace"
 tables=json.loads(sql(DB,query));total=sum(t['bytes'] for t in tables)
 assert not any(t['table']=='price_bar' and t['schema']!='control649' for t in tables),'HISTORY_NOT_OPERATIONAL_BACKUP'
 assert total<1024**3 and shutil.disk_usage(work).free>total*3+2*1024**3,'BACKUP_DISK_LIMIT'
 target='launch649_restore_'+generation.lower().replace('-','_')
 assert sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+target+"'")=='0','RESTORE_TARGET_EXISTS'
 keeper=subprocess.Popen(['docker','exec','-i',CONTAINER,'psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',DB],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 keeper.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n');keeper.stdin.flush()
 snapshot=keeper.stdout.readline().strip();assert re.fullmatch(r'[A-Fa-f0-9-]+',snapshot),'SNAPSHOT_NOT_EXPORTED'
 proof=[];created=False;began=time.monotonic()
 try:
  run(['pg_dump','-U','postgres','-d',DB,'--schema-only','--no-owner','--no-acl','--snapshot='+snapshot,'-f',inside+'/schema.sql'])
  ddl=(work/'schema.sql').read_bytes()
  assert not re.search(rb'(?:AKIA[A-Z0-9]{16}|sk-ant-[A-Za-z0-9_-]{10,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY)',ddl),'SCHEMA_SECRET_PATTERN'
  args=['pg_dump','-U','postgres','-d',DB,'-Fc','--data-only','--no-owner','--no-acl','--snapshot='+snapshot,'-f',inside+'/operational.dump']
  for t in tables:args+=['-t',t['schema']+'.'+t['table']]
  run(args)
  for t in tables:
   name='"'+t['schema']+'"."'+t['table']+'"'
   stmt="SELECT json_build_object('rows',count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),''))) FROM "+name+' t'
   source=json.loads(sql(DB,"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '"+snapshot+"'; "+stmt+'; COMMIT;'))
   proof.append({'table':t['schema']+'.'+t['table'],'source':source,'query':stmt})
  keeper.stdin.write('ROLLBACK;\n\\q\n');keeper.stdin.flush();keeper.wait(timeout=10)
  run(['createdb','-U','postgres',target]);created=True
  sql('postgres','REVOKE CONNECT ON DATABASE '+target+' FROM PUBLIC')
  run(['psql','-Xq','-v','ON_ERROR_STOP=1','-U','postgres','-d',target,'-f',inside+'/schema.sql'])
  run(['pg_restore','-U','postgres','-d',target,'--exit-on-error','--disable-triggers','--no-owner','--no-acl',inside+'/operational.dump'])
  for row in proof:
   restored=json.loads(sql(target,row.pop('query')))
   assert restored==row['source'],'RESTORE_ROW_HASH_MISMATCH'
   row['matches']=True
  assert sql(target,"SELECT count(*) FROM pg_constraint WHERE NOT convalidated AND connamespace IN ('application'::regnamespace,'ai'::regnamespace,'control649'::regnamespace)")=='0','UNVALIDATED_OPERATIONAL_CONSTRAINT'
 finally:
  if keeper.poll() is None:
   keeper.stdin.close();keeper.wait(timeout=10)
  if created:run(['dropdb','-U','postgres',target])
 result={'status':'RESTORED_ALL_SELECTED_TABLES','generation':generation,'tables':proof,'tableCount':len(proof),'selectedBytes':total,'elapsedSeconds':round(time.monotonic()-began,2),'mvccSameSnapshot':True,'temporaryDatabaseRemoved':True,'marketHistoryIncluded':False,'excludedDerivedTables':['application.price_bar_quality_issue'],'sessionCredentialsExcluded':True}
 (work/'proof.json').write_text(json.dumps(result,sort_keys=True))
 files=[{'name':n,'path':str(work/n),'bytes':(work/n).stat().st_size,'sha256':digest(work/n)} for n in ['schema.sql','operational.dump','proof.json']]
 return {'status':result['status'],'generation':generation,'tableCount':len(proof),'selectedBytes':total,'files':files,'elapsedSeconds':result['elapsedSeconds'],'mvccSameSnapshot':True,'temporaryDatabaseRemoved':True}

def upload(manifest):
 import urllib.request
 assert manifest['generation'] in str(manifest['files'][0]['path']),'GENERATION_PATH_MISMATCH'
 for item in manifest['files']:
  p=Path(item['path']);assert '/operational649/' in str(p) and digest(p)==item['sha256'],'IMMUTABLE_BACKUP_FILE_CHANGED'
  # A short-lived single-key presigned PUT, passed only in private SSM memory.
  request=urllib.request.Request(item['url'],data=p.read_bytes(),method='PUT',headers=item['headers'])
  with urllib.request.urlopen(request,timeout=120) as r:assert r.status==200,'BACKUP_UPLOAD_FAILED'
 return {'uploaded':len(manifest['files']),'generation':manifest['generation']}

if __name__=='__main__':
 try:
  action=sys.argv[1]
  result=stage(sys.argv[2]) if action=='stage' else upload(json.loads(sys.stdin.read()))
  print(json.dumps(result))
 except Exception as e:
  failure={'status':'FAILED','type':type(e).__name__,'code':str(e) if isinstance(e,AssertionError) and re.fullmatch('[A-Z_]+',str(e)) else 'PRIVATE_BACKUP_ERROR'}
  Path('/opt/trader649/runtime/backup-last-failure.json').write_text(json.dumps(failure));print(json.dumps(failure));raise SystemExit(1)
