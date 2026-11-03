import json,subprocess,shutil
from pathlib import Path
root=Path('/opt/trader-runtime/launch659');plan=json.loads((root/'disk-plan.json').read_text())
checks=[]
for x in plan['matched']:
 c=json.loads(subprocess.check_output(['docker','inspect',x['preserved']['container']]))[0]
 image=json.loads(subprocess.check_output(['docker','image','inspect',x['preserved']['imageId']]))[0]
 assert image['Id']==x['preserved']['imageId'],'PRESERVED_IMAGE_MISSING'
 checks.append(not Path(x['path']).exists() and c['Image']==x['preserved']['imageId'])
current=json.loads(subprocess.check_output(['docker','inspect','trader-backend']))[0]
result={'removedDuplicateJars':sum(checks),'matchedBytes':plan['recoverableBytes'],'beforeFreeMiB':plan['beforeFreeMiB'],'afterFreeMiB':shutil.disk_usage('/').free//2**20,'preservedCopiesVerified':all(checks),'currentBackendImage':current['Config']['Image'],'currentBackendRunning':current['State']['Running'],'images':subprocess.check_output(['docker','image','ls','-q','--no-trunc'],text=True).splitlines(),'containerNames':subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()}
assert all(checks) and current['State']['Running'] and 'password655b' in current['Config']['Image'],'READBACK_FAILED'
(root/'disk-readback.json').write_text(json.dumps(result));print(json.dumps(result))
