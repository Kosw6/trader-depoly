"""Exact installed CPU role start/drain. TERM only; no force kill or budget reset."""
import json,os,subprocess,time,sys
from pathlib import Path
ROOT=Path('/opt/trader649/runtime');CONFIG=ROOT/'config.json'
def command(args):return subprocess.run(args,capture_output=True,text=True,timeout=75)
def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name]))[0]
def allowed(config):
 from datetime import datetime
 from zoneinfo import ZoneInfo
 now=datetime.now(ZoneInfo('Asia/Seoul'))
 override=ROOT/'override-until'
 return (now.date().isoformat()>=config['activationDate'] and now.hour>=9) or (override.exists() and float(override.read_text())>time.time())
def gate(config):
 if not allowed(config):raise SystemExit(1)
 return {'allowed':True}
def start(config,minutes=0):
 assert 0<=minutes<=120,'OVERRIDE_LIMIT'
 if minutes:(ROOT/'override-until').write_text(str(time.time()+minutes*60))
 gate(config)
 # Boot-time window rejection can exhaust systemd's start budget. Reset only
 # after the time/maintenance gate has explicitly permitted this start.
 r=command(['systemctl','reset-failed','docker.service','docker.socket']);assert r.returncode==0,'DOCKER_RESET_FAILED'
 r=command(['systemctl','start','docker']);assert r.returncode==0,'DOCKER_START_FAILED'
 # A boot rejected by Docker's time gate also leaves dependent oneshots failed.
 # Restore the installed private endpoint mappings before any consumers start.
 if Path('/etc/systemd/system/trader-endpoint-aliases649.service').exists():
  assert command(['systemctl','reset-failed','trader-endpoint-aliases649.service']).returncode==0,'ALIAS_RESET_FAILED'
  assert command(['systemctl','start','trader-endpoint-aliases649.service']).returncode==0,'PRIVATE_ENDPOINT_ALIAS_FAILED'
 for name,policy in reversed(list(config['restartPolicies'].items())):
  assert command(['docker','update','--restart='+policy,name]).returncode==0,'RESTART_POLICY_FAILED'
  if not inspect(name)['State']['Running']:assert command(['docker','start',name]).returncode==0,'ROLE_START_FAILED'
 if config['role']=='origin':Path('/run/trader-maintenance649').unlink(missing_ok=True)
 return {'startedApprovedContainersOnly':True,'role':config['role'],'count':len(config['restartPolicies'])}
def stop(config):
 if config['role']=='origin':Path('/run/trader-maintenance649').write_text('scheduled maintenance')
 if command(['systemctl','is-active','docker']).returncode!=0:
  assert command(['pgrep','-f','^/usr/bin/containerd-shim']).returncode==1,'DOCKER_DOWN_LIVE_SHIMS_HELD'
  return {'role':config['role'],'graceful':True,'dockerNotStarted':True,'forcedKillIssued':False}
 rows=[]
 for name in config['restartPolicies']:
  x=inspect(name);assert command(['docker','update','--restart=no',name]).returncode==0,'FENCE_RESTART_FAILED'
  if x['State']['Running']:
   assert command(['docker','kill','--signal','TERM',name]).returncode==0,'NORMAL_TERM_FAILED'
   until=time.monotonic()+60
   while time.monotonic()<until and inspect(name)['State']['Running']:time.sleep(.5)
  x=inspect(name);s=x['State'];row={'name':name,'running':s['Running'],'exit':s['ExitCode'],'oom':s['OOMKilled']};rows.append(row)
  assert not s['Running'] and not s['OOMKilled'] and s['ExitCode'] in (0,143),'ROLE_DRAIN_HELD_NO_FORCE'
 return {'role':config['role'],'graceful':True,'containers':rows,'forcedKillIssued':False}
def audit(config):
 if config['role']!='database':return {'containers':[{'name':n,'running':inspect(n)['State']['Running']} for n in config['restartPolicies']]}
 query="SELECT json_build_object('prepared',(SELECT count(*) FROM pg_prepared_xacts),'unfinished',(SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() AND (xact_start IS NOT NULL OR state='idle in transaction')),'activeCollectorItems',(SELECT count(*) FROM control649.pipeline_job_item WHERE status IN ('RUNNING','COLLECTING','PUBLISHING')),'activeIndexJobs',(SELECT count(*) FROM ai.index_job WHERE status='RUNNING'));"
 r=command(['docker','exec','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated','-c',query]);assert r.returncode==0,'STOP_SQL_AUDIT_FAILED'
 data=json.loads(r.stdout);assert all(v==0 for v in data.values()),'STOP_UNFINISHED_WORK_HELD';return data
if __name__=='__main__':
 try:
  c=json.loads(CONFIG.read_text());action=sys.argv[1]
  r=gate(c) if action=='gate' else start(c,int(sys.argv[2]) if len(sys.argv)>2 else 0) if action=='start' else stop(c) if action=='stop' else audit(c)
  print(json.dumps(r))
 except Exception as e:
  print(json.dumps({'status':'HOLD','type':type(e).__name__,'code':str(e) if isinstance(e,AssertionError) else 'PRIVATE_RUNTIME_ERROR'}));raise SystemExit(1)
