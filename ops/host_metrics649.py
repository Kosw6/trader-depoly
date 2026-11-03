"""Internal read-only metrics. Never emits envs, command lines, paths, or user labels."""
import http.client,json,os,shutil,socket,time
import sqlite3
from contextlib import closing
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

CONFIG=Path('/opt/trader649/metrics.json')
API_VERSION=None

def budget_usage(path,limit):
 assert 0<int(limit)<=20_000_000
 # Read-only URI never provisions or resets the production ledger.
 with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True,timeout=0.2)) as db:
  db.execute('PRAGMA query_only=ON')
  used=db.execute('SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM calls WHERE month=?',(datetime.now(timezone.utc).strftime('%Y-%m'),)).fetchone()[0]
 assert used>=0
 return used,int(limit)

class Docker(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(2);self.sock.connect('/var/run/docker.sock')

def collect(config):
 global API_VERSION
 rows=[]
 def metric(name,value,labels=''):
  rows.append('trader_'+name+('{'+labels+'}' if labels else '')+' '+str(value))
 mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
 metric('memory_available_bytes',mem['MemAvailable']);metric('memory_total_bytes',mem['MemTotal'])
 metric('load1',os.getloadavg()[0]);metric('cpu_count',os.cpu_count());metric('boot_timestamp_seconds',int(Path('/proc/stat').read_text().split('btime ')[1].split()[0]))
 for name,path in config['disks'].items():
  v=shutil.disk_usage(path);label='disk="'+name+'"';metric('disk_free_bytes',v.free,label);metric('disk_total_bytes',v.total,label)
 try:
  if API_VERSION is None:
   c=Docker('localhost',timeout=2);c.request('GET','/version');r=c.getresponse();version=json.loads(r.read())['ApiVersion'];assert r.status==200 and version.replace('.','').isdigit();API_VERSION=version
  prefix='/v'+API_VERSION
  c=Docker('localhost',timeout=2);c.request('GET',prefix+'/containers/json?all=true');r=c.getresponse();data=json.loads(r.read());assert r.status==200
  candidates={n[1:]:x for x in data for n in x.get('Names',[])}
  for name in config['containers']:
   value=candidates.get(name);metric('container_running',int(bool(value and value['State']=='running')),'container="'+name+'"')
   if value:
    c=Docker('localhost',timeout=2);c.request('GET',prefix+'/containers/'+value['Id']+'/json');r=c.getresponse();x=json.loads(r.read());assert r.status==200
    label='container="'+name+'"';metric('container_restart_total',x.get('RestartCount',0),label);metric('container_oom_killed',int(x['State'].get('OOMKilled',False)),label)
    metric('container_memory_limit_bytes',x['HostConfig']['Memory'],label)
  metric('docker_inspection_success',1)
 except Exception:metric('docker_inspection_success',0)
 if config.get('budgetLedger'):
  try:
   used,limit=budget_usage(config['budgetLedger'],config['budgetLimitMicroUSD'])
   metric('api_budget_used_micro_usd',used);metric('api_budget_limit_micro_usd',limit);metric('api_budget_read_success',1)
  except Exception:metric('api_budget_read_success',0)
 return '\n'.join(rows)+'\n'

class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/metrics':self.send_error(404);return
  try:
   body=collect(self.server.config).encode();self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  except Exception:self.send_error(503,'metrics unavailable')
 def log_message(self,*args):pass

if __name__=='__main__':
 config=json.loads(CONFIG.read_text());server=ThreadingHTTPServer((config['bind'],9141),Handler);server.config=config;server.serve_forever()
