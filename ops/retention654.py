"""Expire timestamped records in stopped-container logs; preserve unknown records."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import gzip,json,os,re,stat,subprocess,tempfile

def expire_json_lines(path,cutoff):
 path=Path(path);assert not path.is_symlink(),'LOG_SYMLINK_REJECTED'
 old=path.stat();opener=gzip.open if path.suffix=='.gz' else open
 fd,tmp=tempfile.mkstemp(prefix='.privacy654-',dir=path.parent);os.close(fd)
 removed=kept=unknown=0
 try:
  with opener(path,'rb') as source,opener(tmp,'wb') as target:
   for line in source:
    expired=False
    try:
     stamp=json.loads(line)['time'];when=datetime.fromisoformat(stamp.replace('Z','+00:00'))
     if when.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
     expired=when<cutoff
    except (ValueError,KeyError,TypeError,AttributeError):unknown+=1
    if expired:removed+=1
    else:target.write(line);kept+=1
  if removed:
   os.chmod(tmp,stat.S_IMODE(old.st_mode))
   if hasattr(os,'chown'):os.chown(tmp,old.st_uid,old.st_gid)
   with open(tmp,'r+b') as f:os.fsync(f.fileno())
   os.replace(tmp,path)
  return {'removed':removed,'kept':kept,'unknownPreserved':unknown}
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def main():
 subprocess.run(['journalctl','--rotate'],check=True,capture_output=True)
 subprocess.run(['journalctl','--vacuum-time=30d'],check=True,capture_output=True)
 counts={'removed':0,'kept':0,'unknownPreserved':0,'files':0};cutoff=datetime.now(timezone.utc)-timedelta(days=30)
 for name in subprocess.check_output(['docker','ps','-aq'],text=True).splitlines():
  x=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
  if x['State']['Running'] or x['HostConfig']['LogConfig']['Type']!='json-file' or not x.get('LogPath'):continue
  p=Path(x['LogPath']);base=Path('/var/lib/docker/containers').resolve()
  assert not p.is_symlink() and p.resolve().is_relative_to(base) and p.parent.name==x['Id'],'LOG_PATH_REVIEW'
  for f in p.parent.glob(p.name+'*'):
   if not re.fullmatch(re.escape(p.name)+r'(?:\.\d+)?(?:\.gz)?',f.name) or not f.is_file():continue
   assert not f.is_symlink(),'LOG_SYMLINK_REJECTED'
   result=expire_json_lines(f,cutoff);counts['files']+=1
   for k,v in result.items():counts[k]+=v
 receipt=Path('/opt/trader-runtime/privacy654/retention-last-run.json')
 receipt.write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),**counts}));receipt.chmod(0o600)
 print(json.dumps(counts))
if __name__=='__main__':main()
