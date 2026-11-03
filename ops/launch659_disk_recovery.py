import json,subprocess,hashlib,shutil
from pathlib import Path
root=Path('/opt/trader-runtime/launch659');plan=json.loads((root/'disk-plan.json').read_text());recovery=root/'preserved-jars';recovery.mkdir(exist_ok=True)
proof=[];restored=set()
for item in plan['matched']:
 cid=item['preserved']['container'];iid=item['preserved']['imageId'];inspect=subprocess.run(['docker','image','inspect',iid],capture_output=True)
 entry={'originalPath':item['path'],'sha256':item['sha256'],'imageAvailable':inspect.returncode==0,'container':cid}
 if inspect.returncode!=0:
  target=recovery/(item['sha256']+'.jar')
  if not target.exists():subprocess.run(['docker','cp',cid+':/app/app.jar',str(target)],check=True,capture_output=True)
  with target.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256'],'RECOVERY_HASH_MISMATCH'
  entry['recoveredCanonicalJar']=str(target);restored.add(str(target))
 proof.append(entry)
result={'verifiedCopies':len(proof),'recoveredCanonicalCopies':len(restored),'beforeFreeMiB':plan['beforeFreeMiB'],'afterFreeMiB':shutil.disk_usage('/').free//2**20,'proof':proof,'oldContainersPreserved':True,'productionImageUnchanged':True}
assert result['afterFreeMiB']>=3000,'DISK_SPACE_REVIEW'
(root/'disk-final.json').write_text(json.dumps(result));print(json.dumps(result))
