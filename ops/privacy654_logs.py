"""Install bounded journal retention and preserve stopped container rollback metadata."""
from pathlib import Path
import json,subprocess,time,copy,socket,http.client,os

def run(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=180)
 assert r.returncode==0,'LOG_CONFIGURATION_COMMAND_FAILED'
 return r.stdout
def inspect(name):return json.loads(run(['docker','inspect',name]))[0]
class Docker(http.client.HTTPConnection):
 def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.connect('/var/run/docker.sock')
def api(method,path,body=None):
 c=Docker('localhost',timeout=180);c.request(method,'/v'+VERSION+path,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
 r=c.getresponse();data=r.read();assert r.status<300,'DOCKER_LOG_MIGRATION_FAILED';return json.loads(data) if data else None
def drain(name):
 run(['docker','update','--restart=no',name])
 if inspect(name)['State']['Running']:run(['docker','kill','--signal','TERM',name])
 until=time.monotonic()+75
 while inspect(name)['State']['Running'] and time.monotonic()<until:time.sleep(.5)
 assert not inspect(name)['State']['Running'],'NORMAL_LOG_DRAIN_HELD_NO_FORCE'

def install():
 root=Path('/opt/trader-runtime/privacy654');root.mkdir(parents=True,exist_ok=True,mode=0o700)
 drop=Path('/etc/systemd/journald.conf.d/654-retention.conf');drop.parent.mkdir(exist_ok=True)
 drop.write_text('[Journal]\nMaxRetentionSec=30day\nMaxFileSec=1day\nSystemMaxUse=256M\nRuntimeMaxUse=64M\n')
 run(['systemctl','restart','systemd-journald'])
 config=json.loads(Path('/opt/trader649/runtime/config.json').read_text());rows=[]
 for name in config['restartPolicies']:
  if name=='trader-data-shared649':continue # network/volume keeper has no application request processing
  old=inspect(name)
  if old['HostConfig']['LogConfig']['Type']=='journald':rows.append({'name':name,'journal':True,'alreadyConfigured':True});continue
  prior=name+'-before654logs';assert subprocess.run(['docker','inspect',prior],capture_output=True).returncode!=0,'LOG_MIGRATION_ALREADY_STARTED'
  saved=root/(name+'-before-private.json');saved.write_text(json.dumps(old));saved.chmod(0o600)
  cfg=copy.deepcopy(old['Config']);host=copy.deepcopy(old['HostConfig']);host['LogConfig']={'Type':'journald','Config':{'tag':'revest/{{.Name}}'}}
  bound={x.split(':')[1] for x in host.get('Binds') or [] if ':' in x}
  for mount in old['Mounts']:
   if mount['Type']=='volume' and mount['Destination'] not in bound:host.setdefault('Binds',[]).append(mount['Name']+':'+mount['Destination']+('' if mount['RW'] else ':ro'))
  cfg['HostConfig']=host
  drain(name);run(['docker','rename',name,prior])
  try:
   api('POST','/containers/create?name='+name,cfg)
   if old['State']['Running']:api('POST','/containers/'+name+'/start')
   now=inspect(name)
   assert {m['Destination']:m['Source'] for m in now['Mounts']}=={m['Destination']:m['Source'] for m in old['Mounts']},'LOG_MIGRATION_VOLUME_CHANGED'
   assert now['State']['Running']==old['State']['Running'],'LOG_MIGRATION_STATE_CHANGED'
  except Exception:
   if subprocess.run(['docker','inspect',name],capture_output=True).returncode==0:drain(name);run(['docker','rename',name,name+'-failed654logs'])
   run(['docker','rename',prior,name]);run(['docker','update','--restart='+old['HostConfig']['RestartPolicy']['Name'],name])
   if old['State']['Running']:run(['docker','start',name])
   raise
  rows.append({'name':name,'journal':True,'mountsUnchanged':True,'rollback':prior})
 cleanup=root/'cleanup.py'
 cleanup.write_text(globals().get('CLEANUP_SOURCE') or Path(__file__).with_name('retention654.py').read_text(encoding='utf-8-sig'));cleanup.chmod(0o700)
 Path('/etc/systemd/system/revest-privacy654-retention.service').write_text('[Unit]\nAfter=docker.service\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /opt/trader-runtime/privacy654/cleanup.py\n')
 Path('/etc/systemd/system/revest-privacy654-retention.timer').write_text('[Unit]\nDescription=Revest bounded operational log retention\n[Timer]\nOnBootSec=2min\nOnCalendar=daily\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
 run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','revest-privacy654-retention.timer'])
 nginx=Path('/etc/logrotate.d/nginx')
 if nginx.exists():
  import re
  body=nginx.read_text();(root/'nginx-logrotate-before.txt').write_text(body)
  body=re.sub(r'\brotate\s+\d+','rotate 14',body)
  if 'maxage ' not in body:body=body.replace('{','{\n    maxage 30',1)
  nginx.write_text(body)
 return {'role':config['role'],'journalRetentionDays':30,'rotationSeconds':86400,'timerEnabled':True,'containers':rows,'oldStoppedLogExpiryDays':30}

if __name__=='__main__':
 VERSION=run(['docker','version','--format','{{.Server.APIVersion}}']).strip()
 try:print(json.dumps(install()))
 except Exception as e:print(json.dumps({'status':'FAILED','code':str(e) if isinstance(e,AssertionError) else type(e).__name__}));raise SystemExit(1)
