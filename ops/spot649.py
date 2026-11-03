"""IMDSv2 notice handling; no AWS start/stop APIs, no forced container kill."""
import json,os,subprocess,time,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path('/opt/trader649');CONFIG=ROOT/'spot-config.json'

def atomic(path,value):
 temp=path.with_suffix('.pending');temp.write_text(json.dumps(value,sort_keys=True));temp.chmod(0o600)
 with temp.open('rb') as f:os.fsync(f.fileno())
 os.replace(temp,path)

def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name]))[0]

def drain(config,reason):
 rows=[]
 for name in config['stopOrder']:
  x=inspect(name)
  subprocess.run(['docker','update','--restart=no',name],check=True,capture_output=True)
  if x['State']['Running']:
   subprocess.run(['docker','kill','--signal','TERM',name],check=True,capture_output=True)
   deadline=time.monotonic()+55
   while time.monotonic()<deadline:
    x=inspect(name)
    if not x['State']['Running']:break
    time.sleep(.5)
  x=inspect(name)
  row={'name':name,'running':x['State']['Running'],'exit':x['State']['ExitCode'],'oom':x['State']['OOMKilled']};rows.append(row)
  if row['running'] or row['oom'] or row['exit']!=0:
   return {'graceful':False,'reason':reason,'containers':rows,'forcedKillIssued':False}
 return {'graceful':True,'reason':reason,'containers':rows,'forcedKillIssued':False}

def start(config):
 for name in reversed(config['stopOrder']):
  subprocess.run(['docker','update','--restart='+config['restartPolicies'][name],name],check=True,capture_output=True)
  if not inspect(name)['State']['Running']:subprocess.run(['docker','start',name],check=True,capture_output=True)
 return {'startedApprovedContainersOnly':True,'containers':list(reversed(config['stopOrder']))}

def serve(config):
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));token=None;renew=0
 boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();events=ROOT/'spot-events';events.mkdir(mode=0o700,exist_ok=True)
 while True:
  try:
   if time.monotonic()>=renew:
    req=urllib.request.Request('http://169.254.169.254/latest/api/token',method='PUT',headers={'X-aws-ec2-metadata-token-ttl-seconds':'21600'})
    with opener.open(req,timeout=2) as f:token=f.read().decode()
    renew=time.monotonic()+18000
   req=urllib.request.Request('http://169.254.169.254/latest/meta-data/spot/instance-action',headers={'X-aws-ec2-metadata-token':token})
   with opener.open(req,timeout=2) as f:notice=json.load(f)
   if notice.get('action') not in ['stop','terminate','hibernate']:raise ValueError('unknown notice')
   receipt=events/(boot+'.json');value={'bootId':boot,'noticedAtUtc':datetime.now(timezone.utc).isoformat(),'notice':notice,'role':config['role'],'status':'DRAINING'};atomic(receipt,value)
   outcome=drain(config,'REAL_IMDSV2_SPOT_NOTICE');value.update({'status':'DRAINED' if outcome['graceful'] else 'HOLD_REVIEW','outcome':outcome,'finishedAtUtc':datetime.now(timezone.utc).isoformat()});atomic(receipt,value)
   # Keep the service alive, without repeated drains or EC2 API actions.
   while True:time.sleep(30)
  except urllib.error.HTTPError as e:
   if e.code!=404:token=None;renew=0
  except Exception:
   atomic(events/(boot+'-observation-error.json'),{'bootId':boot,'atUtc':datetime.now(timezone.utc).isoformat(),'status':'NOTICE_OBSERVATION_ERROR','noForcedAction':True});token=None;renew=0
  time.sleep(5)

if __name__=='__main__':
 import sys
 config=json.loads(CONFIG.read_text())
 if sys.argv[1]=='serve':serve(config)
 elif sys.argv[1]=='start':print(json.dumps(start(config)))
 elif sys.argv[1]=='drain':print(json.dumps(drain(config,'AUTHORIZED_GRACEFUL_DRAIN')))
