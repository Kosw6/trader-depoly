"""Console buttons and scheduled CPU lifecycle; no GPU, run-instances or force kill."""
import os,json,time,uuid,hashlib,base64,subprocess,re
from datetime import datetime
from zoneinfo import ZoneInfo
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
CONFIG=json.loads(os.environ['OPERATIONS_CONFIG'])
CLIENTS={}
def client(name):
 if name not in CLIENTS:CLIENTS[name]=boto3.client(name,config=Config(connect_timeout=5,read_timeout=35,retries={'total_max_attempts':1}))
 return CLIENTS[name]
def remote(role,code,label,timeout=600):
 compile(code,'daily649','exec');ssm=client('ssm');identity=CONFIG['roles'][role]
 encoded=base64.b64encode(code.encode()).decode()
 wrapper="import base64,json\ntry:\n exec(compile(base64.b64decode("+repr(encoded)+"),'daily649','exec'))\nexcept Exception as e:\n print(json.dumps({'status':'HOLD','type':type(e).__name__}));raise SystemExit(1)"
 sent=ssm.send_command(InstanceIds=[identity],DocumentName='AWS-RunShellScript',Comment=('649 '+label)[:100],Parameters={'commands':["python3 - <<'PY'\n"+wrapper+"\nPY"],'executionTimeout':[str(timeout)]})
 cid=sent['Command']['CommandId'];until=time.monotonic()+timeout+5
 while time.monotonic()<until:
  time.sleep(2)
  try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=identity)
  except ssm.exceptions.InvocationDoesNotExist:continue
  if r['Status'] in ('Pending','Delayed','InProgress'):continue
  assert r['Status']=='Success','SSM_OPERATION_HELD'
  return json.loads(r['StandardOutputContent'])
 raise TimeoutError('SSM_UNKNOWN_OUTCOME_NO_REPLAY')
def host(role,action,minutes=0):
 prefix=''
 if action=='start':
  from pathlib import Path
  body=Path(__file__).with_name('runtime649_host.py').read_text(encoding='utf8')
  prefix="from pathlib import Path\np=Path('/opt/trader649/runtime/runtime.py');p.write_text("+repr(body)+",encoding='utf8');p.chmod(0o700)\n"
 return remote(role,prefix+"import subprocess,json\nr=subprocess.run(['python3','/opt/trader649/runtime/runtime.py',"+repr(action)+","+repr(str(minutes))+"],capture_output=True,text=True,timeout=300)\nassert r.returncode==0,'HOST_CONTRACT_HELD'\nprint(r.stdout)",action+' '+role,timeout=330)
def states():
 return {x['InstanceId']:x for r in client('ec2').describe_instances(InstanceIds=list(CONFIG['roles'].values()))['Reservations'] for x in r['Instances']}
def wait_states(ids,wanted,seconds=180):
 until=time.monotonic()+seconds
 while time.monotonic()<until:
  rows=states()
  if all(rows[n]['State']['Name']==wanted for n in ids):return rows
  time.sleep(3)
 raise TimeoutError('EC2_STATE_UNCONFIRMED')
def online(role):
 identity=CONFIG['roles'][role];ssm=client('ssm');until=time.monotonic()+150
 while time.monotonic()<until:
  rows=ssm.describe_instance_information(Filters=[{'Key':'InstanceIds','Values':[identity]}])['InstanceInformationList']
  if rows and rows[0]['PingStatus']=='Online':return
  time.sleep(3)
 raise TimeoutError('ROLE_SSM_OFFLINE')
def get_state(key):
 row=client('dynamodb').get_item(TableName=CONFIG['table'],Key={'id':{'S':key}},ConsistentRead=True).get('Item',{})
 return json.loads(row.get('value',{}).get('S','{}'))
def put_state(key,value):
 client('dynamodb').put_item(TableName=CONFIG['table'],Item={'id':{'S':key},'value':{'S':json.dumps(value,sort_keys=True)}})
def notify(subject,code):
 return client('sns').publish(TopicArn=CONFIG['topicArn'],Subject=subject,Message=json.dumps(code,ensure_ascii=False))['MessageId']
def public_ready():
 import urllib.request
 until=time.monotonic()+240
 while time.monotonic()<until:
  try:
   with urllib.request.urlopen('https://revestlab.com/ai-api/health/ready',timeout=8) as r:
    if r.status==200:return True
  except Exception:pass
  time.sleep(3)
 raise TimeoutError('PUBLIC_READINESS_UNCONFIRMED')

def start_existing(ids,seconds=120):
 # EC2 may report stopped before its persistent Spot request is disabled.
 # Only this known transition is re-observed; capacity/auth/unknown errors hold.
 until=time.monotonic()+seconds
 while True:
  try:client('ec2').start_instances(InstanceIds=ids);return
  except ClientError as error:
   if error.response.get('Error',{}).get('Code')!='IncorrectSpotRequestState':raise
   current=states()
   if not all(current[n]['State']['Name']=='stopped' for n in ids):raise
   if time.monotonic()>=until:raise TimeoutError('SPOT_STOP_TRANSITION_UNCONFIRMED') from error
   time.sleep(5)
def start(event):
 maintenance=int(event.get('maintenanceMinutes',0));assert 0<=maintenance<=120,'MAINTENANCE_LIMIT'
 put_state('DESIRED',{'state':'STARTING','overrideUntil':time.time()+maintenance*60})
 started=[]
 for group in [['database','redis','kafka'],['embedding'],['origin','controller']]:
  before=states();targets=[CONFIG['roles'][r] for r in group if before[CONFIG['roles'][r]]['State']['Name']=='stopped']
  assert all(before[CONFIG['roles'][r]]['State']['Name'] in ('stopped','running') for r in group),'START_STATE_HELD'
  if targets:start_existing(targets);started+=targets;wait_states(targets,'running')
  for role in group:online(role);host(role,'start',maintenance)
 origin=states()[CONFIG['roles']['origin']];ip=origin.get('PublicIpAddress');assert ip,'ORIGIN_PUBLIC_ADDRESS_MISSING'
 client('route53').change_resource_record_sets(HostedZoneId=CONFIG['zone'],ChangeBatch={'Changes':[{'Action':'UPSERT','ResourceRecordSet':{'Name':'origin.revestlab.com.','Type':'A','TTL':60,'ResourceRecords':[{'Value':ip}]}}]})
 public_ready();put_state('DESIRED',{'state':'RUNNING','overrideUntil':time.time()+maintenance*60})
 return {'status':'STARTED','roles':list(CONFIG['roles']),'newlyStarted':len(started),'originDnsRefreshed':True,'publicReady':True,'spotOnDemandFallback':False}
def backup():
 import operations649
 operations649.backup()
 from pathlib import Path
 return json.loads(Path('/tmp/launch649/operations/backup-verified.json').read_text())
def ledger():
 generation=datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
 key='backups/daily-operational649/ledgers/'+generation+'/budget.sqlite3'
 code=r'''
from pathlib import Path
import sqlite3,json,hashlib,os
os.umask(0o077);source=Path('/opt/trader-runtime/cpu626/state/budget.sqlite3');root=Path('/opt/trader649/runtime/ledgers');root.mkdir(mode=0o700,exist_ok=True)
target=root/GENERATION;assert not target.exists()
with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as a,sqlite3.connect(target) as b:a.backup(b)
with sqlite3.connect(target) as b:
 assert b.execute('pragma integrity_check').fetchone()[0]=='ok'
 tables=[r[0] for r in b.execute("select name from sqlite_master where type='table'")]
 for n in tables:
  columns=[x[1].lower() for x in b.execute('pragma table_info("'+n+'")')]
  assert not any(c in ['question','prompt','api_key','password','secret','context_token'] for c in columns)
body=target.read_bytes();print(json.dumps({'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'base64':__import__('base64').b64encode(body).decode()}))
'''
 # Ledger may exceed SSM's 24 KiB output. Upload directly from host instead.
 url=client('s3').generate_presigned_url('put_object',Params={'Bucket':CONFIG['bucket'],'Key':key,'ServerSideEncryption':'AES256','IfNoneMatch':'*'},ExpiresIn=600)
 code=code.replace("body=target.read_bytes();print(json.dumps({'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'base64':__import__('base64').b64encode(body).decode()}))", "import urllib.request\nbody=target.read_bytes();request=urllib.request.Request(URL,data=body,method='PUT',headers={'x-amz-server-side-encryption':'AES256','If-None-Match':'*'})\nwith urllib.request.urlopen(request,timeout=60) as f:assert f.status==200\nprint(json.dumps({'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'integrityCheck':'ok','cumulativeLedgerUnmodified':True}))")
 result=remote('origin','GENERATION='+repr(generation)+'\nURL='+repr(url)+'\n'+code,'anonymous cumulative ledger exact SQLite backup',timeout=150)
 body=client('s3').get_object(Bucket=CONFIG['bucket'],Key=key)['Body'].read();assert hashlib.sha256(body).hexdigest()==result['sha256'],'LEDGER_S3_SHA_MISMATCH'
 result['key']=key
 proof=json.dumps(result,sort_keys=True).encode()
 client('s3').put_object(Bucket=CONFIG['bucket'],Key=key.rsplit('/',1)[0]+'/verified.json',Body=proof,ServerSideEncryption='AES256',IfNoneMatch='*')
 remote('origin',"from pathlib import Path\nimport hashlib,json\np=Path('/opt/trader649/runtime/ledgers')/"+repr(generation)+"\nassert not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()=="+repr(result['sha256'])+"\np.unlink();print(json.dumps({'temporaryLedgerRemoved':True,'liveLedgerUnchanged':True}))",'remove verified temporary ledger only',timeout=30)
 return result
def stop():
 put_state('DESIRED',{'state':'STOPPED'})
 active=states();proof=[]
 for role in ['origin','embedding','controller']:
  if active[CONFIG['roles'][role]]['State']['Name']=='running':online(role);proof.append(host(role,'stop'))
 saved_ledger=ledger() if active[CONFIG['roles']['origin']]['State']['Name']=='running' else {'alreadyStopped':True}
 if active[CONFIG['roles']['database']]['State']['Name']=='running':proof.append(host('database','audit'))
 for role in ['redis','kafka','database']:
  if active[CONFIG['roles'][role]]['State']['Name']=='running':proof.append(host(role,'stop'))
 targets=[n for n,x in states().items() if x['State']['Name']=='running']
 if targets:client('ec2').stop_instances(InstanceIds=targets);wait_states(targets,'stopped')
 assert all(x['State']['Name']=='stopped' for x in states().values()),'STOP_NOT_CONFIRMED'
 return {'status':'ALL_SIX_STOPPED','proof':proof,'finalBudgetBackup':saved_ledger,'forcedKill':False}
def retention():
 s3=client('s3');prefix='backups/daily-operational649/';groups=[]
 for page in s3.get_paginator('list_objects_v2').paginate(Bucket=CONFIG['bucket'],Prefix=prefix,Delimiter='/'):
  for row in page.get('CommonPrefixes',[]):
   name=row['Prefix']
   if name.endswith('/ledgers/'):continue
   if not re.fullmatch(re.escape(prefix)+r'\d{8}T\d{6}Z-[a-z0-9]{6}/',name):continue
   try:s3.head_object(Bucket=CONFIG['bucket'],Key=name+'verified.json');groups.append(name)
   except s3.exceptions.ClientError as e:
    if e.response['ResponseMetadata']['HTTPStatusCode']!=404:raise
 for name in sorted(groups)[:-7]:
  for page in s3.get_paginator('list_object_versions').paginate(Bucket=CONFIG['bucket'],Prefix=name):
   objects=[{'Key':v['Key'],'VersionId':v['VersionId']} for v in page.get('Versions',[])+page.get('DeleteMarkers',[]) if v['Key'].removeprefix(name) in ('schema.sql','operational.dump','proof.json','verified.json')]
   if objects:s3.delete_objects(Bucket=CONFIG['bucket'],Delete={'Objects':objects,'Quiet':True})
 ledger_groups=[]
 for page in s3.get_paginator('list_objects_v2').paginate(Bucket=CONFIG['bucket'],Prefix=prefix+'ledgers/',Delimiter='/'):
  for row in page.get('CommonPrefixes',[]):
   name=row['Prefix']
   if not re.fullmatch(re.escape(prefix)+r'ledgers/\d{8}T\d{6}Z-[a-z0-9]{6}/',name):continue
   try:s3.head_object(Bucket=CONFIG['bucket'],Key=name+'verified.json');ledger_groups.append(name)
   except s3.exceptions.ClientError as e:
    if e.response['ResponseMetadata']['HTTPStatusCode']!=404:raise
 for name in sorted(ledger_groups)[:-7]:
  for page in s3.get_paginator('list_object_versions').paginate(Bucket=CONFIG['bucket'],Prefix=name):
   objects=[{'Key':v['Key'],'VersionId':v['VersionId']} for v in page.get('Versions',[])+page.get('DeleteMarkers',[]) if v['Key'].removeprefix(name) in ('budget.sqlite3','verified.json')]
   if objects:s3.delete_objects(Bucket=CONFIG['bucket'],Delete={'Objects':objects,'Quiet':True})
 return {'verifiedGenerationsKept':min(7,len(groups))}
def alerts():
 desired=get_state('DESIRED');now=datetime.now(ZoneInfo('Asia/Seoul'))
 if now.date().isoformat()<CONFIG['activationDate'] or now.hour<9 or desired.get('state')!='RUNNING':return {'status':'PLANNED_QUIET'}
 body=remote('controller',"import urllib.request,json\nwith urllib.request.urlopen('http://127.0.0.1:9090/api/v1/alerts',timeout=5) as f:b=json.load(f)\nprint(json.dumps([{'alert':x['labels'].get('alertname'),'instance':x['labels'].get('instance'),'severity':x['labels'].get('severity')} for x in b['data']['alerts'] if x['state']=='firing']))",'read only bounded private operational alert labels',timeout=30)
 fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();previous=get_state('ALERTS')
 if previous.get('hash')!=fingerprint:
  if body or previous.get('firing'):notify('Revest Lab 운영 경보' if body else 'Revest Lab 운영 경보 해제',{'alerts':body,'questionsOrKeysIncluded':False})
  put_state('ALERTS',{'hash':fingerprint,'firing':bool(body)})
 return {'firing':len(body),'repeatNotification':False}
def handler(event,context):
 action=event.get('action','status');assert action in ['status','start','backup','stop','alerts','guard','test-notification']
 now=datetime.now(ZoneInfo('Asia/Seoul'))
 if action=='status':return {'states':{k:x['State']['Name'] for k,x in states().items()},'configuration':{'activationDate':CONFIG['activationDate'],'window':'09:00–24:00 Asia/Seoul','gpuAllowed':False}}
 if action=='test-notification':return {'published':bool(notify('Revest Lab 경보 연결 검증',{'test':'launch649','noUserContentOrCredentials':True}))}
 if action=='alerts':return alerts()
 if event.get('scheduled') and now.date().isoformat()<CONFIG['activationDate']:return {'status':'BEFORE_ACTIVATION'}
 desired=get_state('DESIRED')
 if action=='guard':
  identity=event.get('detail',{}).get('instance-id')
  if identity not in [CONFIG['roles']['redis'],CONFIG['roles']['embedding']]:return {'status':'OUT_OF_SCOPE'}
  owner=getattr(context,'aws_request_id',None) or uuid.uuid4().hex;ddb=client('dynamodb')
  try:
   ddb.put_item(TableName=CONFIG['table'],Item={'id':{'S':'LOCK'},'owner':{'S':owner},'until':{'N':str(int(time.time())+920)}},ConditionExpression='attribute_not_exists(id) OR #u < :now',ExpressionAttributeNames={'#u':'until'},ExpressionAttributeValues={':now':{'N':str(int(time.time()))}})
  except ClientError as error:
   if error.response['Error']['Code']=='ConditionalCheckFailedException':return {'status':'LIFECYCLE_IN_PROGRESS'}
   raise
  try:
   # Re-read under the same lease as start/stop, never act on a stale desire.
   desired=get_state('DESIRED')
   if desired.get('state') in ('STARTING','RUNNING') and (now.date().isoformat()>=CONFIG['activationDate'] and now.hour>=9 or desired.get('overrideUntil',0)>time.time()):return {'status':'WINDOW_ALLOWED'}
   if states()[identity]['State']['Name']=='stopped':return {'status':'ALREADY_STOPPED'}
   role=next(r for r,n in CONFIG['roles'].items() if n==identity);online(role);host(role,'stop');client('ec2').stop_instances(InstanceIds=[identity]);wait_states([identity],'stopped');return {'status':'OUTSIDE_WINDOW_SPOT_STOPPED'}
  finally:ddb.delete_item(TableName=CONFIG['table'],Key={'id':{'S':'LOCK'}},ConditionExpression='#o=:owner',ExpressionAttributeNames={'#o':'owner'},ExpressionAttributeValues={':owner':{'S':owner}})
 if action=='start' and now.hour<9 and not event.get('maintenanceMinutes'):raise ValueError('EXPLICIT_MAINTENANCE_OVERRIDE_REQUIRED')
 operation=(now.date().isoformat()+'-'+action) if event.get('scheduled') else event.get('requestId',context.aws_request_id)
 prior=get_state('OP#'+operation)
 if prior:return {'status':'ALREADY_RECORDED','previousStatus':prior['status'],'operation':operation}
 owner=context.aws_request_id;ddb=client('dynamodb')
 ddb.put_item(TableName=CONFIG['table'],Item={'id':{'S':'LOCK'},'owner':{'S':owner},'until':{'N':str(int(time.time())+920)}},ConditionExpression='attribute_not_exists(id) OR #u < :now',ExpressionAttributeNames={'#u':'until'},ExpressionAttributeValues={':now':{'N':str(int(time.time()))}})
 put_state('OP#'+operation,{'status':'RUNNING'})
 try:
  result=start(event) if action=='start' else stop() if action=='stop' else {'backup':backup(),'retention':retention()}
  put_state('OP#'+operation,{'status':'COMPLETE','result':result});return result
 except Exception as e:
  safe={'status':'HOLD','action':action,'type':type(e).__name__,'automaticReplay':False};put_state('OP#'+operation,safe);notify('Revest Lab 자동 운영 확인 필요',safe);raise
 finally:ddb.delete_item(TableName=CONFIG['table'],Key={'id':{'S':'LOCK'}},ConditionExpression='#o=:owner',ExpressionAttributeNames={'#o':'owner'},ExpressionAttributeValues={':owner':{'S':owner}})
