import json,subprocess,hashlib,tarfile,shutil
from pathlib import Path
root=Path('/opt/trader-runtime/launch659');root.mkdir(mode=0o700,exist_ok=True)
candidates=[p for base in ['/opt/trader-runtime/releases','/opt/trader-runtime/cutover555'] for p in Path(base).rglob('*.jar') if p.is_file() and not p.is_symlink() and p.stat().st_size>100*1024**2]
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
files=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in candidates]
names=subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
proof={};seen=set()
for n in names:
 if not n.startswith('trader-backend'):continue
 x=json.loads(subprocess.check_output(['docker','inspect',n]))[0]
 if x['Image'] in seen:continue
 seen.add(x['Image'])
 proc=subprocess.Popen(['docker','cp',n+':/app/app.jar','-'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 digest=None
 try:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
   for entry in archive:
    if entry.isfile():
     h=hashlib.sha256();f=archive.extractfile(entry)
     while block:=f.read(1048576):h.update(block)
     digest=h.hexdigest()
 except tarfile.TarError:pass
 code=proc.wait(timeout=30)
 if code==0 and digest:proof[digest]={'container':n,'imageId':x['Image']}
matched=[dict(f,preserved=proof[f['sha256']]) for f in files if f['sha256'] in proof]
result={'beforeFreeMiB':shutil.disk_usage('/').free//2**20,'matched':matched,'unmatched':[f['path'] for f in files if f['sha256'] not in proof],'recoverableBytes':sum(f['bytes'] for f in matched),'imagesRemoved':0,'containersRemoved':0}
(root/'disk-plan.json').write_text(json.dumps(result));print(json.dumps(result))
