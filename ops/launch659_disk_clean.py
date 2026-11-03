import json,hashlib,subprocess,shutil
from pathlib import Path
root=Path('/opt/trader-runtime/launch659');plan=json.loads((root/'disk-plan.json').read_text())
assert len(plan['matched'])==17 and not plan['unmatched'],'CLEAN_PLAN_REVIEW'
def inventory():
 return {'images':sorted(subprocess.check_output(['docker','image','ls','-q','--no-trunc'],text=True).splitlines()),'containers':sorted(subprocess.check_output(['docker','ps','-aq','--no-trunc'],text=True).splitlines())}
before=inventory();free=shutil.disk_usage('/').free
for item in plan['matched']:
 p=Path(item['path']);resolved=p.resolve()
 assert not p.is_symlink() and any(resolved.is_relative_to(Path(base)) for base in ['/opt/trader-runtime/releases','/opt/trader-runtime/cutover555']),'PATH_OUTSIDE_RELEASES'
 assert p.suffix=='.jar' and p.stat().st_size==item['bytes'],'FILE_CHANGED'
 with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256'],'COPY_HASH_CHANGED'
 x=json.loads(subprocess.check_output(['docker','inspect',item['preserved']['container']]))[0]
 assert x['Image']==item['preserved']['imageId'],'PRESERVED_IMAGE_CHANGED'
 assert all(m['Source']!=str(p) for m in x.get('Mounts',[])),'DIRECT_RUNTIME_MOUNT'
for item in plan['matched']:Path(item['path']).unlink()
assert inventory()==before,'RUNTIME_INVENTORY_CHANGED'
result={'removedDuplicateJars':len(plan['matched']),'matchedBytes':plan['recoverableBytes'],'beforeFreeMiB':free//2**20,'afterFreeMiB':shutil.disk_usage('/').free//2**20,'allImagesAndContainersPreserved':True,'databaseAndUserDataTouched':False}
assert result['afterFreeMiB']>=3000,'SPACE_TARGET_NOT_REACHED'
(root/'disk-complete.json').write_text(json.dumps(result));print(json.dumps(result))
