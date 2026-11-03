import json,subprocess,hashlib,tarfile
from pathlib import Path
rows=[]
for base in ['/opt/trader-runtime/releases','/opt/trader-runtime/cutover555']:
 for p in Path(base).rglob('*'):
  if p.is_file() and not p.is_symlink() and p.stat().st_size>25*1024**2:
   rows.append({'path':str(p),'bytes':p.stat().st_size,'suffix':p.suffix})
print(json.dumps({'files':rows}))
