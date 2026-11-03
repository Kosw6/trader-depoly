import json,subprocess,shutil
from pathlib import Path
def cmd(args):return subprocess.check_output(args,text=True).strip()
rows=[]
for n in cmd(['docker','ps','-a','--format','{{.Names}}']).splitlines():
 x=json.loads(cmd(['docker','inspect',n]))[0]
 rows.append({'name':n,'image':x['Config']['Image'],'imageId':x['Image'],'running':x['State']['Running'],'mounts':[{'type':m['Type'],'source':m['Source'],'destination':m['Destination']} for m in x.get('Mounts',[])]})
sizes=[]
for p in ['/opt/trader-runtime','/var/lib/docker','/var/log','/var/cache/apt/archives','/tmp']:
 r=subprocess.run(['du','-x','-B1','--max-depth=2',p],capture_output=True,text=True)
 lines=[]
 for line in r.stdout.splitlines():
  size,path=line.split('\t',1)
  if int(size)>30*1024**2:lines.append({'bytes':int(size),'path':path})
 sizes+=sorted(lines,key=lambda x:x['bytes'],reverse=True)[:16]
print(json.dumps({'freeMiB':shutil.disk_usage('/').free//2**20,'containers':rows,'largeDirectories':sizes,'dockerUsage':cmd(['docker','system','df'])}))
